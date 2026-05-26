"""Tests for B-7 batch reservation services.

Coverage:
    * ``create_batch_reservation`` — happy path + 6 walidation failure modes
    * ``bulk_confirm_batch`` — confirms only OCZEKUJACA, skip others
    * ``bulk_cancel_batch`` — cancels OCZEKUJACA + POTWIERDZONA, skip closed
    * ``bulk_change_operator_batch`` — changes operator on active only
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from machines.models import Machine
from reservations.factories import (
    CancelledReservationFactory,
    CompletedReservationFactory,
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation
from reservations.services import (
    MAX_BATCH_MACHINES,
    bulk_cancel_batch,
    bulk_change_operator_batch,
    bulk_confirm_batch,
    create_batch_reservation,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def machines_three(db):
    """Trzy maszyny w stanie W_MAGAZYNIE — gotowe do batch'a."""
    return [
        Machine.objects.create(
            uid=f"BAT-{i:03d}",
            name=f"Maszyna batch {i}",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        for i in range(1, 4)
    ]


# =============================================================================
# create_batch_reservation
# =============================================================================


@pytest.mark.django_db
class TestCreateBatchReservation:
    def test_creates_n_reservations_with_same_batch_id(self, machines_three):
        """Happy path: 3 maszyny → 3 rezerwacje, wszystkie z tym samym batch_id."""
        result = create_batch_reservation(
            machine_ids=[m.pk for m in machines_three],
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="Kierownik Test",
            today=date(2030, 5, 1),
        )
        assert result["created_count"] == 3
        assert len(result["reservations"]) == 3
        # Wszystkie mają ten sam batch_id
        batch_ids = {str(r.batch_id) for r in result["reservations"]}
        assert len(batch_ids) == 1
        assert batch_ids.pop() == result["batch_id"]
        # Wszystkie OCZEKUJACA (default status batch'a)
        assert all(r.status == Reservation.Status.OCZEKUJACA for r in result["reservations"])
        # Wszystkie z tym samym person/dates
        assert all(r.person == "Kierownik Test" for r in result["reservations"])
        assert all(r.start_date == date(2030, 6, 1) for r in result["reservations"])
        assert all(r.end_date == date(2030, 6, 5) for r in result["reservations"])

    def test_creates_with_site(self, machines_three, site):
        """Site jest opcjonalne — gdy podane, wszystkie rezerwacje mają ten sam site."""
        result = create_batch_reservation(
            machine_ids=[m.pk for m in machines_three],
            site_id=site.pk,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="Kierownik",
            today=date(2030, 5, 1),
        )
        assert all(r.site_id == site.pk for r in result["reservations"])

    def test_rejects_empty_machine_list(self, db):
        """Pusta lista maszyn → ValidationError."""
        with pytest.raises(ValidationError, match="minimum 1"):
            create_batch_reservation(
                machine_ids=[],
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="Kierownik",
                today=date(2030, 5, 1),
            )

    def test_rejects_too_many_machines(self, db):
        """Powyżej MAX_BATCH_MACHINES → ValidationError ze wzmianką o limicie."""
        # Tworzymy MAX+1 maszyn ale bez zapisu do DB — service rzuca PRZED
        # query do bazy (walidacja długości listy).
        ids = list(range(1, MAX_BATCH_MACHINES + 2))
        with pytest.raises(ValidationError, match=str(MAX_BATCH_MACHINES)):
            create_batch_reservation(
                machine_ids=ids,
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="Kierownik",
                today=date(2030, 5, 1),
            )

    def test_rejects_duplicates_in_machine_list(self, machines_three):
        """Duplikaty w machine_ids → ValidationError."""
        with pytest.raises(ValidationError, match="duplikat"):
            create_batch_reservation(
                machine_ids=[machines_three[0].pk, machines_three[0].pk],
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="Kierownik",
                today=date(2030, 5, 1),
            )

    def test_rejects_unknown_machine_id(self, machines_three):
        """Nieistniejące machine_id → ValidationError z numerem."""
        with pytest.raises(ValidationError, match="99999"):
            create_batch_reservation(
                machine_ids=[machines_three[0].pk, 99999],
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="Kierownik",
                today=date(2030, 5, 1),
            )

    def test_atomic_rollback_on_conflict(self, machines_three):
        """Konflikt na jednej z maszyn → rollback CAŁEGO batch'a (atomic).

        Scenariusz: m2 ma już istniejącą POTWIERDZONA rezerwację w tym
        terminie. Próba batch'a [m1, m2, m3] musi:
          - rzucić ValidationError z informacją o m2,
          - NIE utworzyć żadnej rezerwacji na m1 ani m3 (transaction.atomic).
        """
        m1, m2, m3 = machines_three
        ConfirmedReservationFactory(
            machine=m2,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        before_count = Reservation.objects.count()

        with pytest.raises(ValidationError, match=m2.uid):
            create_batch_reservation(
                machine_ids=[m1.pk, m2.pk, m3.pk],
                site_id=None,
                start_date=date(2030, 6, 3),
                end_date=date(2030, 6, 8),
                person="Kierownik",
                today=date(2030, 5, 1),
            )

        # Atomic guarantee: tylko stara rezerwacja (factory) — żadna nowa.
        after_count = Reservation.objects.count()
        assert after_count == before_count
        # M1 i M3 nie mają żadnej rezerwacji nowo utworzonej (factory była na m2)
        assert not Reservation.objects.filter(machine=m1).exists()
        assert not Reservation.objects.filter(machine=m3).exists()

    def test_rejects_wycofana_machine(self, db, machines_three):
        """Maszyna WYCOFANA w batch'u → ValidationError + rollback."""
        m1, m2, _ = machines_three
        m2.status = Machine.Status.WYCOFANA
        m2.save()
        with pytest.raises(ValidationError, match=m2.uid):
            create_batch_reservation(
                machine_ids=[m1.pk, m2.pk],
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="Kierownik",
                today=date(2030, 5, 1),
            )
        # Rollback: m1 też nie ma rezerwacji
        assert not Reservation.objects.filter(machine=m1).exists()

    def test_rejects_w_serwisie_machine(self, db, machines_three):
        """Maszyna W_SERWISIE w batch'u → ValidationError."""
        m1, m2, _ = machines_three
        m2.status = Machine.Status.W_SERWISIE
        m2.save()
        with pytest.raises(ValidationError, match=m2.uid):
            create_batch_reservation(
                machine_ids=[m1.pk, m2.pk],
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="Kierownik",
                today=date(2030, 5, 1),
            )

    def test_rejects_empty_person(self, machines_three):
        """Pusty person (po stripie) → ValidationError."""
        with pytest.raises(ValidationError):
            create_batch_reservation(
                machine_ids=[machines_three[0].pk],
                site_id=None,
                start_date=date(2030, 6, 1),
                end_date=date(2030, 6, 5),
                person="   ",
                today=date(2030, 5, 1),
            )

    def test_rejects_end_before_start(self, machines_three):
        """end_date < start_date → ValidationError."""
        with pytest.raises(ValidationError):
            create_batch_reservation(
                machine_ids=[machines_three[0].pk],
                site_id=None,
                start_date=date(2030, 6, 10),
                end_date=date(2030, 6, 5),
                person="Kierownik",
                today=date(2030, 5, 1),
            )

    def test_rejects_past_dates(self, machines_three):
        """end_date w przeszłości → ValidationError."""
        with pytest.raises(ValidationError):
            create_batch_reservation(
                machine_ids=[machines_three[0].pk],
                site_id=None,
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 10),
                person="Kierownik",
                today=date(2030, 6, 1),
            )


# =============================================================================
# bulk_confirm_batch
# =============================================================================


@pytest.mark.django_db
class TestBulkConfirmBatch:
    def test_confirms_all_pending(self, machines_three):
        """Wszystkie OCZEKUJACA → POTWIERDZONA jednym wywołaniem."""
        result = create_batch_reservation(
            machine_ids=[m.pk for m in machines_three],
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="K",
            today=date(2030, 5, 1),
        )
        confirm_result = bulk_confirm_batch(result["batch_id"])
        assert confirm_result["confirmed_count"] == 3
        assert confirm_result["skipped_count"] == 0
        # Verify in DB
        statuses = set(
            Reservation.objects.filter(batch_id=result["batch_id"]).values_list("status", flat=True)
        )
        assert statuses == {Reservation.Status.POTWIERDZONA}

    def test_skips_already_confirmed(self, machines_three):
        """Już POTWIERDZONA / inne statusy są skip'owane (idempotent)."""
        result = create_batch_reservation(
            machine_ids=[m.pk for m in machines_three],
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="K",
            today=date(2030, 5, 1),
        )
        # Ręcznie confirm jednej rezerwacji
        first = result["reservations"][0]
        first.status = Reservation.Status.POTWIERDZONA
        first.save()

        # Drugie wywołanie bulk_confirm — 2 confirmed, 1 skipped
        confirm_result = bulk_confirm_batch(result["batch_id"])
        assert confirm_result["confirmed_count"] == 2
        assert confirm_result["skipped_count"] == 1

    def test_rejects_unknown_batch_id(self, db):
        """Nieistniejące batch_id → ValidationError."""
        import uuid

        with pytest.raises(ValidationError, match="nie istnieje"):
            bulk_confirm_batch(uuid.uuid4())


# =============================================================================
# bulk_cancel_batch
# =============================================================================


@pytest.mark.django_db
class TestBulkCancelBatch:
    def test_cancels_all_active(self, machines_three):
        """OCZEKUJACA + POTWIERDZONA → ANULOWANA, ZAKONCZONA skip'owane."""
        # Setup: mix statusów w jednej grupie batch
        import uuid

        batch_id = uuid.uuid4()
        m1, m2, m3 = machines_three
        PendingReservationFactory(machine=m1, batch_id=batch_id)
        ConfirmedReservationFactory(machine=m2, batch_id=batch_id)
        CompletedReservationFactory(machine=m3, batch_id=batch_id)

        result = bulk_cancel_batch(batch_id, reason="klient_zrezygnowal")
        assert result["cancelled_count"] == 2
        assert result["skipped_count"] == 1
        # DB state: 2 anulowane, 1 zakończona (bez zmian)
        statuses = list(
            Reservation.objects.filter(batch_id=batch_id)
            .order_by("machine__uid")
            .values_list("status", flat=True)
        )
        assert statuses.count(Reservation.Status.ANULOWANA) == 2
        assert statuses.count(Reservation.Status.ZAKONCZONA) == 1

    def test_reason_required(self, machines_three):
        """Brak reason → ValidationError."""
        result = create_batch_reservation(
            machine_ids=[machines_three[0].pk],
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="K",
            today=date(2030, 5, 1),
        )
        with pytest.raises(ValidationError, match="Powód"):
            bulk_cancel_batch(result["batch_id"], reason="")

    def test_skips_already_cancelled(self, machines_three):
        """Już ANULOWANA są skip'owane (idempotent)."""
        import uuid

        batch_id = uuid.uuid4()
        m1, m2, _ = machines_three
        CancelledReservationFactory(machine=m1, batch_id=batch_id)
        ConfirmedReservationFactory(machine=m2, batch_id=batch_id)
        result = bulk_cancel_batch(batch_id, reason="awaria")
        assert result["cancelled_count"] == 1  # tylko m2 (m1 już anulowana)
        assert result["skipped_count"] == 1


# =============================================================================
# bulk_change_operator_batch
# =============================================================================


@pytest.mark.django_db
class TestBulkChangeOperatorBatch:
    def test_changes_operator_on_active(self, machines_three):
        """OCZEKUJACA + POTWIERDZONA dostają nową osobę, ZAKONCZONA skip."""
        import uuid

        batch_id = uuid.uuid4()
        m1, m2, m3 = machines_three
        PendingReservationFactory(machine=m1, batch_id=batch_id, person="Tomek Kowalski")
        ConfirmedReservationFactory(machine=m2, batch_id=batch_id, person="Tomek Kowalski")
        CompletedReservationFactory(machine=m3, batch_id=batch_id, person="Tomek Kowalski")

        result = bulk_change_operator_batch(batch_id, new_person="Sven Olsen")
        assert result["changed_count"] == 2
        assert result["skipped_count"] == 1
        # Active mają nową osobę, zakończona ma starą
        persons = dict(
            Reservation.objects.filter(batch_id=batch_id).values_list("machine__uid", "person")
        )
        assert persons[m1.uid] == "Sven Olsen"
        assert persons[m2.uid] == "Sven Olsen"
        assert persons[m3.uid] == "Tomek Kowalski"

    def test_rejects_short_name(self, machines_three):
        """new_person < MIN_OPERATOR_NAME_LENGTH → ValidationError."""
        result = create_batch_reservation(
            machine_ids=[machines_three[0].pk],
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="K",
            today=date(2030, 5, 1),
        )
        with pytest.raises(ValidationError):
            bulk_change_operator_batch(result["batch_id"], new_person="XY")

    def test_skips_same_person(self, machines_three):
        """Gdy new_person == current_person (case-insensitive) → skip (idempotent re-run)."""
        result = create_batch_reservation(
            machine_ids=[m.pk for m in machines_three],
            site_id=None,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
            person="Sven Olsen",
            today=date(2030, 5, 1),
        )
        # Drugie wywołanie z tym samym imieniem → wszystkie skip'owane
        change_result = bulk_change_operator_batch(result["batch_id"], new_person="sven olsen")
        assert change_result["changed_count"] == 0
        assert change_result["skipped_count"] == 3
