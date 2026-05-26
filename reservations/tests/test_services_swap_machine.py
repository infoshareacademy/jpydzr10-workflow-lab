"""Testy serwisu ``swap_machine`` — wymiana maszyny mid-reservation (B-6).

Pokrywa:

* happy path — KOP-001 ZAKONCZONA, KOP-002 POTWIERDZONA, FK ``replaced_by`` set,
* preserved fields — person / site / address / end_date przeniesione na nową,
* machine flip — stara maszyna → W_SERWISIE (best-effort),
* notatki audit — banner "Wymieniona na X" w starej, "Wymiana po awarii Y" w nowej,
* guards: zamknięta, identyczna maszyna, wycofana, konflikt w pozostałym okresie,
* atomicity — failed validation nie zostawia śladu,
* best-effort fallback — stara maszyna z innymi rezerwacjami zostaje bez zmian,
* widok integracji — POST + redirect do NOWEJ rezerwacji + perm guard.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import (
    CancelledReservationFactory,
    CompletedReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation
from reservations.services import swap_machine


@pytest.fixture
def actor(db):
    user_model = get_user_model()
    return user_model.objects.create_user(
        username="magazynierka",
        password="secret-pw-123!",
        first_name="Maria",
        last_name="Kowalska",
    )


@pytest.fixture
def replacement_machine(db):
    """Druga maszyna dostępna jako zastępcza (KOP-002)."""
    return Machine.objects.create(
        uid="KOP-002",
        name="Koparka zastępcza",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


@pytest.mark.django_db
class TestSwapMachineHappy:
    """Happy path — wymiana powiodła się, oba rezerwacje w spójnym stanie."""

    @freeze_time("2026-06-15")
    def test_basic_swap_closes_old_creates_new(self, machine, replacement_machine, site, actor):
        """Klasyczny scenariusz Tomek: KOP-001 confirmed → KOP-002 swap."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        original = ConfirmedReservationFactory(
            machine=machine,
            site=site,
            person="Tomek Nowak",
            address="Polna 5, Kraków",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
            notes="Pilne",
        )

        result = swap_machine(
            original,
            new_machine=replacement_machine,
            reason="Awaria silnika KOP-001",
            actor=actor,
        )

        # Oryginalna rezerwacja — zamknięta dziś, replaced_by set.
        original.refresh_from_db()
        assert original.status == Reservation.Status.ZAKONCZONA
        assert original.end_date == date(2026, 6, 15)
        assert original.replaced_by_id == result["new_id"]
        assert "Wymieniona na KOP-002" in original.notes
        assert "Awaria silnika KOP-001" in original.notes

        # Nowa rezerwacja — potwierdzona, pokrywa pozostały okres.
        new_res = Reservation.objects.get(pk=result["new_id"])
        assert new_res.machine_id == replacement_machine.pk
        assert new_res.status == Reservation.Status.POTWIERDZONA
        assert new_res.start_date == date(2026, 6, 15)
        assert new_res.end_date == date(2026, 6, 20)
        assert new_res.person == "Tomek Nowak"
        assert new_res.site_id == site.pk
        assert new_res.address == "Polna 5, Kraków"
        assert "Wymiana po awarii maszyny KOP-001" in new_res.notes
        assert f"#{original.pk}" in new_res.notes

        # Maszyna oryginalna — best-effort → W_SERWISIE (brak future rezerwacji).
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_SERWISIE
        assert result["machine_to_service_uid"] == "KOP-001"

    @freeze_time("2026-06-15")
    def test_swap_preserves_replaced_by_link(self, machine, replacement_machine, actor):
        """FK replaced_by jest poprawnie ustawione (bezpośredni assert)."""
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )

        swap_machine(original, new_machine=replacement_machine, actor=actor)

        original.refresh_from_db()
        assert original.replaced_by is not None
        # reverse — z nowej możemy dostać się do starej via related_name="replaces"
        new = original.replaced_by
        assert original in list(new.replaces.all())

    @freeze_time("2026-06-15")
    def test_swap_works_for_pending_reservation(self, machine, replacement_machine, actor):
        """Pending reservation też pozwala swap (jeszcze nie potwierdzona)."""
        original = PendingReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 16),
            end_date=date(2026, 6, 20),
        )

        result = swap_machine(original, new_machine=replacement_machine, actor=actor)

        original.refresh_from_db()
        assert original.status == Reservation.Status.ZAKONCZONA
        new = Reservation.objects.get(pk=result["new_id"])
        assert new.status == Reservation.Status.POTWIERDZONA

    @freeze_time("2026-06-15")
    def test_swap_without_reason_omits_suffix(self, machine, replacement_machine, actor):
        """Brak reason — notatki bez " : powód" suffix."""
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
            notes="",
        )

        result = swap_machine(original, new_machine=replacement_machine, actor=actor)

        original.refresh_from_db()
        new = Reservation.objects.get(pk=result["new_id"])
        # "[Wymieniona na KOP-002 (rezerwacja #N) dnia 2026-06-15]" — bez ": powód"
        assert "Wymieniona na KOP-002" in original.notes
        assert "dnia 2026-06-15" in original.notes
        assert ":" not in original.notes.rsplit("dnia 2026-06-15", 1)[-1]
        assert "Wymiana po awarii maszyny KOP-001" in new.notes

    @freeze_time("2026-06-15")
    def test_swap_with_empty_reason_treated_as_none(self, machine, replacement_machine, actor):
        """Empty/whitespace reason zachowuje się jak brak reason."""
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )

        swap_machine(
            original,
            new_machine=replacement_machine,
            reason="   ",  # whitespace only
            actor=actor,
        )

        original.refresh_from_db()
        # Nie powinno być pustego ": " w notatkach
        assert ": " not in original.notes.split("dnia")[-1]

    @freeze_time("2026-06-15")
    def test_swap_overdue_reservation_uses_today_as_end(self, machine, replacement_machine, actor):
        """Hard Return Policy edge — overdue rezerwacja (end_date < today).

        Pozostały okres = [today, today] (minimum 1 dzień), nie cofamy w przeszłość.
        """
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        # end_date w przeszłości względem 2026-06-15
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 10),
        )

        result = swap_machine(original, new_machine=replacement_machine, actor=actor)

        new = Reservation.objects.get(pk=result["new_id"])
        assert new.start_date == date(2026, 6, 15)
        # remaining_end = max(end_date, today) = max(2026-06-10, 2026-06-15) = today
        assert new.end_date == date(2026, 6, 15)

    @freeze_time("2026-06-15")
    def test_swap_history_user_set_on_both_reservations(self, machine, replacement_machine, actor):
        """history_user na nowej (utworzenie) i starej (zamknięcie) = actor."""
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )

        result = swap_machine(original, new_machine=replacement_machine, actor=actor)

        original.refresh_from_db()
        new = Reservation.objects.get(pk=result["new_id"])
        # Najnowszy rekord historii starej zawiera actor. Ordering po
        # ``-history_id`` (PK historical) bo freeze_time zamraża
        # ``history_date`` i dwa wpisy mają identyczny timestamp.
        latest_old = original.history.order_by("-history_id").first()
        assert latest_old.history_user_id == actor.pk
        # Najnowszy rekord historii nowej (utworzenie) też.
        latest_new = new.history.order_by("-history_id").first()
        assert latest_new.history_user_id == actor.pk


@pytest.mark.django_db
class TestSwapMachineGuards:
    """Validation + business-rule guards."""

    def test_closed_completed_reservation_cannot_swap(self, machine, replacement_machine, actor):
        original = CompletedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="zamkniętej"):
            swap_machine(original, new_machine=replacement_machine, actor=actor)

    def test_closed_cancelled_reservation_cannot_swap(self, machine, replacement_machine, actor):
        original = CancelledReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="zamkniętej"):
            swap_machine(original, new_machine=replacement_machine, actor=actor)

    def test_same_machine_rejected(self, machine, actor):
        original = ConfirmedReservationFactory(machine=machine)
        with pytest.raises(ValidationError, match="różnić"):
            swap_machine(original, new_machine=machine, actor=actor)

    def test_retired_machine_rejected(self, machine, actor):
        original = ConfirmedReservationFactory(machine=machine)
        retired = Machine.objects.create(
            uid="KOP-RETIRED",
            name="Wycofana",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.WYCOFANA,
        )
        with pytest.raises(ValidationError, match="wycofana"):
            swap_machine(original, new_machine=retired, actor=actor)

    @freeze_time("2026-06-15")
    def test_conflict_on_replacement_machine_rejected(self, machine, replacement_machine, actor):
        """Zastępcza maszyna ma kolidującą rezerwację w okresie [today, end]."""
        # Konflikt: KOP-002 ma już rezerwację 2026-06-17 - 2026-06-22.
        ConfirmedReservationFactory(
            machine=replacement_machine,
            start_date=date(2026, 6, 17),
            end_date=date(2026, 6, 22),
        )
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )

        with pytest.raises(ValidationError, match="kolidujących"):
            swap_machine(original, new_machine=replacement_machine, actor=actor)

    @freeze_time("2026-06-15")
    def test_failed_validation_does_not_create_new_or_mutate_old(
        self, machine, replacement_machine, actor
    ):
        """Atomicity: rzucony ValidationError nie zostawia śladu w DB."""
        # Konflikt — zapewniamy że swap_machine padnie.
        ConfirmedReservationFactory(
            machine=replacement_machine,
            start_date=date(2026, 6, 14),
            end_date=date(2026, 6, 18),
        )
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )
        original_status = original.status
        original_end = original.end_date
        # Liczba rezerwacji przed swap'em (konflikt + original = 2).
        reservations_before = Reservation.objects.count()

        with pytest.raises(ValidationError):
            swap_machine(original, new_machine=replacement_machine, actor=actor)

        original.refresh_from_db()
        # Stan starej zachowany.
        assert original.status == original_status
        assert original.end_date == original_end
        assert original.replaced_by is None
        # Nowa rezerwacja NIE powstała.
        assert Reservation.objects.count() == reservations_before


@pytest.mark.django_db
class TestSwapMachineSideEffects:
    """Side-effects — flip statusu maszyny, best-effort fallback."""

    @freeze_time("2026-06-15")
    def test_original_machine_moved_to_service(self, machine, replacement_machine, actor):
        """Po swap'ie stara maszyna → W_SERWISIE (gdy brak future rezerwacji)."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )

        result = swap_machine(original, new_machine=replacement_machine, actor=actor)

        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_SERWISIE
        assert result["machine_to_service_uid"] == "KOP-001"

    @freeze_time("2026-06-15")
    def test_machine_with_future_bookings_not_moved_to_service(
        self, machine, replacement_machine, actor
    ):
        """Best-effort fallback — gdy stara maszyna ma future rezerwacje,
        ``set_machine_to_service`` rzuca, łapiemy, swap się powiódł, maszyna
        zostaje w status NA_BUDOWIE (bez zmiany — operator decyduje ręcznie).
        """
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        # Aktywna do swap'a.
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 20),
        )
        # KOP-001 ma future booking po 25 czerwca — blokuje to W_SERWISIE.
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2026, 6, 25),
            end_date=date(2026, 6, 30),
        )

        result = swap_machine(original, new_machine=replacement_machine, actor=actor)

        # Swap się powiódł.
        original.refresh_from_db()
        assert original.status == Reservation.Status.ZAKONCZONA
        new = Reservation.objects.get(pk=result["new_id"])
        assert new.status == Reservation.Status.POTWIERDZONA

        # Ale stara maszyna NIE poszła do serwisu.
        machine.refresh_from_db()
        assert machine.status == Machine.Status.NA_BUDOWIE
        assert result["machine_to_service_uid"] == ""


@pytest.mark.django_db
class TestSwapMachineView:
    """Integration testy widoku — POST + flash + redirect + perm."""

    def test_view_swaps_and_redirects_to_new_reservation(
        self, client_logged, machine, replacement_machine
    ):
        """View redirects do NOWEJ rezerwacji (nie starej — bo ta jest historyczna)."""
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        original = ConfirmedReservationFactory(
            machine=machine,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=10),
            person="Tomek",
        )

        response = client_logged.post(
            reverse("reservations:swap_machine", args=[original.pk]),
            data={
                "new_machine": replacement_machine.pk,
                "reason": "Awaria silnika",
            },
        )

        assert response.status_code == 302
        # Redirect to NEW reservation, NOT original.
        original.refresh_from_db()
        new_id = original.replaced_by_id
        assert response.url.endswith(f"/rezerwacje/{new_id}/")
        # Origin zamknięta, nowa potwierdzona.
        assert original.status == Reservation.Status.ZAKONCZONA
        new = Reservation.objects.get(pk=new_id)
        assert new.status == Reservation.Status.POTWIERDZONA
        assert new.person == "Tomek"

    def test_view_rejects_missing_new_machine(self, client_logged, machine):
        original = ConfirmedReservationFactory(machine=machine)

        response = client_logged.post(
            reverse("reservations:swap_machine", args=[original.pk]),
            data={"new_machine": "", "reason": ""},
        )

        assert response.status_code == 302
        assert response.url.endswith(f"/rezerwacje/{original.pk}/")
        original.refresh_from_db()
        assert original.status == Reservation.Status.POTWIERDZONA
        assert original.replaced_by is None

    def test_view_rejects_same_machine_via_service(self, client_logged, machine):
        """Same machine — service rejects, flash error."""
        original = ConfirmedReservationFactory(machine=machine)

        response = client_logged.post(
            reverse("reservations:swap_machine", args=[original.pk]),
            data={"new_machine": machine.pk, "reason": ""},
        )

        assert response.status_code == 302
        # Forma odsiewa current_machine z queryset → "Wybierz prawidłową opcję" error
        # → flash + redirect z powrotem do oryginalnej.
        assert response.url.endswith(f"/rezerwacje/{original.pk}/")
        original.refresh_from_db()
        assert original.replaced_by is None

    def test_view_requires_permission(self, client_no_perms, machine, replacement_machine):
        original = ConfirmedReservationFactory(machine=machine)
        response = client_no_perms.post(
            reverse("reservations:swap_machine", args=[original.pk]),
            data={"new_machine": replacement_machine.pk},
        )
        assert response.status_code == 403

    def test_view_requires_post(self, client_logged, machine):
        original = ConfirmedReservationFactory(machine=machine)
        response = client_logged.get(reverse("reservations:swap_machine", args=[original.pk]))
        assert response.status_code == 405

    def test_view_404_for_missing_pk(self, client_logged, replacement_machine):
        response = client_logged.post(
            reverse("reservations:swap_machine", args=[99999]),
            data={"new_machine": replacement_machine.pk},
        )
        assert response.status_code == 404

    def test_view_rejects_closed_reservation(self, client_logged, machine, replacement_machine):
        original = CompletedReservationFactory(machine=machine)
        response = client_logged.post(
            reverse("reservations:swap_machine", args=[original.pk]),
            data={"new_machine": replacement_machine.pk},
        )
        assert response.status_code == 302
        original.refresh_from_db()
        assert original.replaced_by is None


@pytest.mark.django_db
class TestSwapMachineDetailContext:
    """Detail view eksponuje SwapMachineForm w context (na potrzeby modala)."""

    def test_swap_form_in_context_for_open_reservation(
        self, client_logged, machine, replacement_machine
    ):
        original = ConfirmedReservationFactory(machine=machine)
        response = client_logged.get(reverse("reservations:detail", args=[original.pk]))
        assert response.status_code == 200
        assert "swap_machine_form" in response.context
        form = response.context["swap_machine_form"]
        # Queryset zawiera replacement_machine, NIE zawiera obecnej.
        machines_in_form = list(form.fields["new_machine"].queryset)
        assert replacement_machine in machines_in_form
        assert machine not in machines_in_form

    def test_swap_form_absent_for_closed_reservation(self, client_logged, machine):
        original = CompletedReservationFactory(machine=machine)
        response = client_logged.get(reverse("reservations:detail", args=[original.pk]))
        assert response.status_code == 200
        # Modal i form ukryte dla zamkniętych — context nie zawiera form.
        assert response.context.get("swap_machine_form") is None
