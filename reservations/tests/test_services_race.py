"""Race-condition tests for confirm/cancel/complete services.

Klasyczne race-condition na transitions:

* dwóch managerów klika "Zatwierdź" na tej samej rezerwacji w tej samej
  sekundzie — bez ``select_for_update`` obaj przeszliby check na statusie
  ``OCZEKUJACA``, obaj wykonaliby UPDATE → race-conditioned double commit.
* dwóch managerów zatwierdza nakładające się PENDING dla tej samej maszyny —
  bez recheck conflicts pod lockiem, oba sprawdzą "no conflict" jeszcze
  zanim pierwszy zapisał, oba zapiszą POTWIERDZONA → overlapping bookings.

Testy w tym module pokrywają oba scenariusze w sposób deterministyczny
(symulujemy "współbieżność" ręcznie poprzez modyfikację stanu między
``has_conflict`` a ``save``).
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from reservations.factories import PendingReservationFactory
from reservations.models import Reservation
from reservations.services import confirm_reservation


@pytest.mark.django_db
class TestConfirmReservationRaceSafety:
    """Race-safety guards w :func:`confirm_reservation`."""

    def test_re_fetches_under_lock_before_status_change(self, machine):
        """Symulacja: status zmieniony przez równoległą transakcję.

        Po wywołaniu z "stale" referencją do PENDING, service powinien
        ponownie pobrać aktualny stan z DB pod lockiem. Jeśli równolegle
        ktoś zmienił status (np. anulował), service wykryje to przez
        :func:`_assert_legal_transition` i rzuci ValidationError zamiast
        nadpisać zmianę.
        """
        res = PendingReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        # Symulacja zewnętrznej anulacji (np. inny manager kliknął "Anuluj"
        # między pobraniem ``res`` a wywołaniem ``confirm_reservation``).
        Reservation.objects.filter(pk=res.pk).update(status=Reservation.Status.ANULOWANA)
        # ``res`` w pamięci nadal ma status OCZEKUJACA, ale baza ma ANULOWANA.
        # Service powinien fetchować pod lockiem i wykryć terminalny stan.
        with pytest.raises(ValidationError, match="Nielegalne przejście"):
            confirm_reservation(res)
        res.refresh_from_db()
        assert res.status == Reservation.Status.ANULOWANA

    def test_concurrent_confirm_detects_conflict_under_lock(self, machine):
        """Conflict recheck pod lockiem łapie race.

        Scenariusz: dwie PENDING rezerwacje nakładające się na tę samą
        maszynę. Pierwsza zostaje POTWIERDZONA (np. przez równoległy
        request). Próba potwierdzenia drugiej powinna złapać konflikt
        pod lockiem (recheck po fetchu) i rzucić ValidationError z
        wiadomością o race condition.
        """
        # PENDING #1 — symulujemy że został potwierdzony równolegle.
        first = PendingReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        Reservation.objects.filter(pk=first.pk).update(status=Reservation.Status.POTWIERDZONA)

        # PENDING #2 — nakłada się na #1, próba confirm musi złapać konflikt.
        second = PendingReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 3),
            end_date=date(2030, 2, 7),
        )
        # Bug 2 fix 2026-05-31: error message zmienione z generic "Konflikt rezerwacji"
        # na konkretna liste konfliktujacych rezerwacji ("nakłada się z N innymi…")
        # zeby user widzial GDZIE konkretnie jest collision.
        with pytest.raises(ValidationError, match="nakłada się"):
            confirm_reservation(second)

        second.refresh_from_db()
        # Druga rezerwacja pozostaje OCZEKUJACA — service NIE nadpisał statusu.
        assert second.status == Reservation.Status.OCZEKUJACA
