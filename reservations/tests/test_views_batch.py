"""View-level tests for B-7 batch reservation.

Coverage:
    * GET ``/rezerwacje/grupa/dodaj/`` renders form
    * POST ``/rezerwacje/grupa/dodaj/`` creates batch + redirects
    * GET ``/rezerwacje/grupa/<uuid>/`` shows reservations
    * POST bulk_confirm / bulk_cancel / bulk_change_operator
    * Permission gating (403 dla user_no_perms)
"""

from __future__ import annotations

import uuid as uuid_mod
from datetime import date, timedelta

import pytest
from django.urls import reverse

from machines.models import Machine
from reservations.factories import ConfirmedReservationFactory, PendingReservationFactory
from reservations.models import Reservation

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def machines_three(db):
    return [
        Machine.objects.create(
            uid=f"BV-{i:03d}",
            name=f"Maszyna view {i}",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        for i in range(1, 4)
    ]


@pytest.fixture
def existing_batch(machines_three):
    """Tworzy istniejący batch (3 OCZEKUJACA na 3 różnych maszynach)."""
    batch_id = uuid_mod.uuid4()
    return {
        "batch_id": batch_id,
        "reservations": [
            PendingReservationFactory(
                machine=m,
                batch_id=batch_id,
                person="Anna Test",
                start_date=date.today() + timedelta(days=5),
                end_date=date.today() + timedelta(days=10),
            )
            for m in machines_three
        ],
    }


# =============================================================================
# batch_create_view
# =============================================================================


@pytest.mark.django_db
class TestBatchCreateView:
    def test_get_renders_form(self, client_logged):
        response = client_logged.get(reverse("reservations:batch_create"))
        assert response.status_code == 200
        # Verify form fields present
        content = response.content.decode("utf-8")
        assert "Maszyny" in content
        assert "Termin" in content
        assert "Wspólne dane" in content

    def test_get_requires_login(self, client):
        response = client.get(reverse("reservations:batch_create"))
        # LoginRequiredMixin / login_required → 302 do /login/
        assert response.status_code == 302

    def test_get_requires_add_permission(self, client_no_perms):
        response = client_no_perms.get(reverse("reservations:batch_create"))
        # permission_required raise_exception=True → 403
        assert response.status_code == 403

    def test_post_creates_batch_and_redirects(self, client_logged, machines_three, site):
        future_start = date.today() + timedelta(days=10)
        future_end = future_start + timedelta(days=5)
        response = client_logged.post(
            reverse("reservations:batch_create"),
            data={
                "machines": [m.pk for m in machines_three],
                "site": site.pk,
                "start_date": future_start.isoformat(),
                "end_date": future_end.isoformat(),
                "person": "Kierownik Testowy",
                "address": "ul. Testowa 1",
                "notes": "Notatka grupowa",
            },
        )
        assert response.status_code == 302
        # Verify 3 reservations created with same batch_id
        reservations = Reservation.objects.filter(person="Kierownik Testowy")
        assert reservations.count() == 3
        batch_ids = {str(r.batch_id) for r in reservations}
        assert len(batch_ids) == 1
        # Redirect target points do batch_detail
        assert "/rezerwacje/grupa/" in response["Location"]

    def test_post_with_no_machines_re_renders_form(self, client_logged):
        response = client_logged.post(
            reverse("reservations:batch_create"),
            data={
                "machines": [],
                "start_date": (date.today() + timedelta(days=1)).isoformat(),
                "end_date": (date.today() + timedelta(days=5)).isoformat(),
                "person": "K",
            },
        )
        # Form re-rendered z błędem (status 200, NIE 302)
        assert response.status_code == 200

    def test_post_with_conflict_re_renders_form_no_partial_create(
        self, client_logged, machines_three
    ):
        """Konflikt na 1 maszynie → 0 rezerwacji utworzonych (atomic rollback)."""
        m1, m2, m3 = machines_three
        future_start = date.today() + timedelta(days=10)
        future_end = future_start + timedelta(days=5)
        # Pre-existing reservation na m2 zachodzi z planowanym batch'em
        ConfirmedReservationFactory(machine=m2, start_date=future_start, end_date=future_end)
        before_count = Reservation.objects.count()

        response = client_logged.post(
            reverse("reservations:batch_create"),
            data={
                "machines": [m1.pk, m2.pk, m3.pk],
                "start_date": future_start.isoformat(),
                "end_date": future_end.isoformat(),
                "person": "Kierownik",
            },
        )
        # Form re-rendered (200) z błędem na __all__
        assert response.status_code == 200
        # Atomic rollback — count się nie zmienił
        assert Reservation.objects.count() == before_count


# =============================================================================
# batch_detail_view
# =============================================================================


@pytest.mark.django_db
class TestBatchDetailView:
    def test_get_renders_batch(self, client_logged, existing_batch):
        response = client_logged.get(
            reverse("reservations:batch_detail", kwargs={"batch_id": existing_batch["batch_id"]})
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Reprezentatywne dane (osoba) widoczne w nagłówku
        assert "Anna Test" in content
        # Wszystkie 3 maszyny w tabeli
        assert "BV-001" in content
        assert "BV-002" in content
        assert "BV-003" in content
        # Akcje bulk widoczne (są pending → potwierdź wszystkie button)
        assert "Potwierd" in content

    def test_get_returns_404_for_unknown_batch(self, client_logged):
        response = client_logged.get(
            reverse(
                "reservations:batch_detail",
                kwargs={"batch_id": uuid_mod.uuid4()},
            )
        )
        assert response.status_code == 404


# =============================================================================
# bulk_confirm view
# =============================================================================


@pytest.mark.django_db
class TestBatchBulkConfirmView:
    def test_post_confirms_all_pending(self, client_logged, existing_batch):
        response = client_logged.post(
            reverse(
                "reservations:batch_bulk_confirm",
                kwargs={"batch_id": existing_batch["batch_id"]},
            )
        )
        assert response.status_code == 302
        # Wszystkie 3 oczekujące → potwierdzone
        statuses = set(
            Reservation.objects.filter(batch_id=existing_batch["batch_id"]).values_list(
                "status", flat=True
            )
        )
        assert statuses == {Reservation.Status.POTWIERDZONA}

    def test_get_not_allowed(self, client_logged, existing_batch):
        """View jest require_POST → GET zwraca 405."""
        response = client_logged.get(
            reverse(
                "reservations:batch_bulk_confirm",
                kwargs={"batch_id": existing_batch["batch_id"]},
            )
        )
        assert response.status_code == 405


# =============================================================================
# bulk_cancel view
# =============================================================================


@pytest.mark.django_db
class TestBatchBulkCancelView:
    def test_post_cancels_all_active(self, client_logged, existing_batch):
        response = client_logged.post(
            reverse(
                "reservations:batch_bulk_cancel",
                kwargs={"batch_id": existing_batch["batch_id"]},
            ),
            data={
                "cancellation_reason": "klient_zrezygnowal",
                "cancellation_note": "Klient odwołał projekt",
            },
        )
        assert response.status_code == 302
        # Wszystkie 3 → anulowane
        cancelled = Reservation.objects.filter(
            batch_id=existing_batch["batch_id"], status=Reservation.Status.ANULOWANA
        )
        assert cancelled.count() == 3
        # Reason zapisany na każdej
        reasons = set(cancelled.values_list("cancellation_reason", flat=True))
        assert reasons == {"klient_zrezygnowal"}

    def test_post_without_reason_re_renders(self, client_logged, existing_batch):
        """Brak reason → flash error + redirect, ale rezerwacje pozostają."""
        response = client_logged.post(
            reverse(
                "reservations:batch_bulk_cancel",
                kwargs={"batch_id": existing_batch["batch_id"]},
            ),
            data={},
        )
        assert response.status_code == 302  # redirect z flash error
        # Wszystkie nadal OCZEKUJACA (bez zmian)
        statuses = set(
            Reservation.objects.filter(batch_id=existing_batch["batch_id"]).values_list(
                "status", flat=True
            )
        )
        assert statuses == {Reservation.Status.OCZEKUJACA}


# =============================================================================
# bulk_change_operator view
# =============================================================================


@pytest.mark.django_db
class TestBatchBulkChangeOperatorView:
    def test_post_changes_operator_on_all_active(self, client_logged, existing_batch):
        response = client_logged.post(
            reverse(
                "reservations:batch_bulk_change_operator",
                kwargs={"batch_id": existing_batch["batch_id"]},
            ),
            data={"new_person": "Sven Olsen"},
        )
        assert response.status_code == 302
        # Wszystkie aktywne (3 oczekujące) → nowa osoba
        persons = set(
            Reservation.objects.filter(batch_id=existing_batch["batch_id"]).values_list(
                "person", flat=True
            )
        )
        assert persons == {"Sven Olsen"}

    def test_post_with_short_name_no_change(self, client_logged, existing_batch):
        """new_person < min_length → flash error + redirect, bez zmian."""
        response = client_logged.post(
            reverse(
                "reservations:batch_bulk_change_operator",
                kwargs={"batch_id": existing_batch["batch_id"]},
            ),
            data={"new_person": "XY"},
        )
        assert response.status_code == 302  # redirect z flash error
        # Osoba bez zmian
        persons = set(
            Reservation.objects.filter(batch_id=existing_batch["batch_id"]).values_list(
                "person", flat=True
            )
        )
        assert persons == {"Anna Test"}
