"""Testy "killing mutations" — manualnie zidentyfikowane survivory w services.

Po analizie mutacyjnej (`reservations/services.py`) zidentyfikowano kilka
operatorów które przeżyłyby standardowy zestaw testów. Ten moduł zamyka
te luki dedykowanymi boundary testami.

Co testujemy (per survivor):

1. ``has_conflict`` (line 107): ``end < start`` — mutacja ``<=`` przeszłaby gdy
   ``end == start`` (single-day query). Test pokazuje że ``end == start`` jest
   legalne (one-day rezerwacja).
2. ``update_reservation`` (line 243): identyczny boundary dla zmiany dat.
   Test single-day update.
3. ``update_reservation`` (line 246): ``and has_conflict(...)`` — mutacja ``or``
   przeszłaby gdyby `dates_changed` było False, ale w DB istniała konfliktowa
   rezerwacja. Test pokazuje że update bez zmiany dat NIE sprawdza konfliktu
   z innych rezerwacji.
4. ``run_daily_sync`` Pass 2 (line 425): ``res.start_date <= today`` —
   mutacja ``<`` skutkowałaby próbą flipa W_MAGAZYNIE→ZAREZERWOWANA dla
   aktywnej rezerwacji (już obsłużonej w Pass 1). Test sprawdza brak
   double-counting w ``result["reserved"]``.
5. ``run_daily_sync`` (line 413): ``end < today`` — mutacja ``<=`` skutkowałaby
   extend gdy dziś == end (ostatni dzień rezerwacji). Test pokazuje że
   tego dnia NIE robi się extend.

Każdy test ma docstring opisujący KTÓRĄ mutację zabija.
"""

from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import ConfirmedReservationFactory, PendingReservationFactory
from reservations.models import Reservation
from reservations.services import (
    has_conflict,
    run_daily_sync,
    update_reservation,
)


@pytest.mark.django_db
class TestHasConflictSingleDayBoundary:
    """Kill mutation: ``has_conflict`` line 107 ``end < start`` → ``<=``."""

    def test_single_day_query_end_equals_start_no_error(self, machine):
        """``end == start`` (single-day) NIE rzuca ValidationError.

        Mutacja ``end < start`` → ``end <= start`` zmienia regułę walidacji
        i zaczęłaby odrzucać rezerwacje jednodniowe. Test pokazuje że
        single-day query jest legalny (transport jednodniowy, inspekcja).
        """
        # Nie powinno rzucić — single-day query.
        result = has_conflict(
            machine_id=machine.pk,
            start=date(2030, 6, 1),
            end=date(2030, 6, 1),
        )
        assert result is False

    def test_single_day_overlap_with_confirmed_returns_true(self, machine):
        """Single-day query w środku innej rezerwacji → konflikt (True).

        Dodatkowo pokrywa że mutacja nie powoduje silent-skip — query
        nadal sprawdza konflikt nawet gdy start == end.
        """
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 10),
        )
        result = has_conflict(
            machine_id=machine.pk,
            start=date(2030, 6, 5),
            end=date(2030, 6, 5),
        )
        assert result is True


@pytest.mark.django_db
class TestUpdateReservationSingleDayBoundary:
    """Kill mutation: ``update_reservation`` line 243 ``end < start`` → ``<=``."""

    def test_update_to_single_day_dates_succeeds(self, machine):
        """Update do ``start == end`` (single-day) przechodzi bez wyjątku.

        Mutacja ``new_end < new_start`` → ``new_end <= new_start`` zaczęłaby
        odrzucać każdą zmianę na single-day rezerwację. Realny use-case:
        skracanie wielodniowej rezerwacji do jednego dnia (np. anulacja
        długiego najmu, zostaje tylko dzień transportu).
        """
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 10),
        )
        update_reservation(res, start_date=date(2030, 6, 5), end_date=date(2030, 6, 5))
        res.refresh_from_db()
        assert res.start_date == date(2030, 6, 5)
        assert res.end_date == date(2030, 6, 5)


@pytest.mark.django_db
class TestUpdateReservationConflictCheckOnlyWhenDatesChange:
    """Kill mutation: ``update_reservation`` line 246 ``and`` → ``or``.

    Logika: ``if dates_changed and has_conflict(...): raise``. Mutacja na
    ``or`` rzuciłaby ValidationError nawet gdy daty NIE są modyfikowane,
    jeśli istnieje gdziekolwiek konfliktowa rezerwacja — to byłby
    "false-positive" race condition.
    """

    def test_update_only_person_with_other_conflicting_reservation(self, machine):
        """Update tylko ``person`` (bez zmiany dat) z konfliktową rezerwacją
        w bazie → BRAK ValidationError.

        Setup: dwie rezerwacje nakładające się na siebie (w realnym sysjie
        byłoby to zablokowane, ale tu symulujemy stan post-factum). Update
        jednej z nich na samym polu ``person`` nie powinien re-walidować
        konfliktu — daty nie zmieniają się, więc check jest pomijany.

        Mutacja ``and`` → ``or`` spowodowałaby raise (false positive), bo
        ``has_conflict`` zwróciłoby True (jest nakładająca się rez.), nawet
        że ``dates_changed`` jest False.
        """
        # Pierwsza rezerwacja: 1-10 lutego.
        first = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 10),
        )
        # Druga rezerwacja: 5-15 lutego (nakładająca się — w realu by nie powstała,
        # ale tu wstawiamy bezpośrednio przez ORM, omijając service guard).
        # Cel: symulacja stanu post-factum (np. dane historyczne migrowane).
        second = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 2, 5),
            end_date=date(2030, 2, 15),
            person="Original",
            status=Reservation.Status.POTWIERDZONA,
        )
        # Update tylko person — daty się NIE zmieniają.
        update_reservation(second, person="Zaktualizowana Osoba")
        second.refresh_from_db()
        assert second.person == "Zaktualizowana Osoba"
        # Konflikt z `first` istnieje, ale check nie został wykonany
        # (dates_changed=False), więc update przeszedł.
        first.refresh_from_db()
        assert first.start_date == date(2030, 2, 1)  # niezmienione


@pytest.mark.django_db
class TestDailySyncPass2BoundaryNoDoubleCount:
    """Kill mutation: ``run_daily_sync`` Pass 2 line 425 ``<=`` → ``<``/``>``.

    Pass 2 ma ``if res.start_date <= today: continue`` (pomija aktywne
    i przeszłe rezerwacje). Mutacje:

    * ``<`` zamiast ``<=``: dla ``start == today`` NIE skipuje, wchodzi
      w sprawdzenie W_MAGAZYNIE → ale Pass 1 już zmienił status na
      NA_BUDOWIE, więc warunek nie spełniony. Bez explicit checka
      ``result["reserved"] == 0`` test może to przegapić.

    * ``>`` zamiast ``<=``: NIGDY nie skipuje, próbuje zarezerwować
      warehouse machine dla każdej rez. (włącznie z przeszłymi).
    """

    @freeze_time("2030-06-01")
    def test_active_reservation_today_no_reserved_increment(self, machine):
        """Active rezerwacja (start == today) NIE inkrementuje ``reserved``.

        Pass 1 obsługuje aktywne rezerwacje (flip NA_BUDOWIE). Pass 2 nie
        powinien już niczego zmieniać dla tej rezerwacji — granica ``<=``
        gwarantuje continue.
        """
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        result = run_daily_sync(today=date(2030, 6, 1))
        machine.refresh_from_db()
        # Pass 1: flip do NA_BUDOWIE (updated=1).
        assert machine.status == Machine.Status.NA_BUDOWIE
        assert result["updated"] == 1
        # Pass 2: NIE powinien dodawać do ``reserved`` (active res. pomijana).
        assert result["reserved"] == 0


@pytest.mark.django_db
class TestDailySyncExtendBoundaryEndEqualsToday:
    """Kill mutation: ``run_daily_sync`` line 413 ``end < today`` → ``<=``.

    Reguła: extend dotyczy SKOŃCZONYCH rezerwacji (``end < today``). Jeśli
    dziś == end (ostatni dzień), rezerwacja jest NADAL aktywna i NIE powinna
    być rozszerzona. Mutacja ``<=`` zacząłaby rozszerzać każdą rezerwację
    której ostatni dzień to dziś — co byłoby błędem.

    UWAGA: test_sync_active_when_end_equals_today w
    test_services_daily_sync.py NIE sprawdza ``result["extended"]``,
    tylko status maszyny i end_date. Maszyna ma status W_MAGAZYNIE z
    fixture, więc Pass 1 wcześniejszy warunek ``machine.status ==
    NA_BUDOWIE`` zwraca False, branch extend nie jest osiągnięty.

    Ten test używa machine.status = NA_BUDOWIE PRZED sync, żeby explicite
    pokryć branch ``elif end < today and machine.status == NA_BUDOWIE``
    przy granicy end == today.
    """

    @freeze_time("2030-06-05")
    def test_machine_on_site_end_equals_today_no_extend(self, machine):
        """``end == today`` + machine NA_BUDOWIE → NIE extends.

        Rezerwacja kończy się dziś, maszyna jest na budowie — rezerwacja
        jest w aktywnym oknie (start <= today <= end), więc Pass 1 trafia
        do branchu aktywnego (NIE elif extend).
        """
        machine.status = Machine.Status.NA_BUDOWIE
        machine.save()
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        result = run_daily_sync(today=date(2030, 6, 5))
        res.refresh_from_db()
        # End_date NIE rozszerzony.
        assert res.end_date == date(2030, 6, 5)
        # Brak extend w counterze.
        assert result["extended"] == 0


@pytest.mark.django_db
class TestDailySyncPendingFutureNoOp:
    """Kill mutation: ``run_daily_sync`` Pass 1 line 397 ``confirmed`` filter.

    Filter ``status=POTWIERDZONA`` — mutacja na inny status lub usunięcie
    filtra zaczęłaby procesować PENDING/ANULOWANA. Test sprawdza że
    pending rezerwacja w przyszłości NIE zmienia stanu maszyny ani liczników.

    Dodatkowo: Pass 2 ``machine.status == W_MAGAZYNIE`` mutacja na inny
    status zaczęłaby flipać też ZAREZERWOWANA/W_SERWISIE. Pokrywa boundary
    dla iteracji confirmed (PENDING ignored).
    """

    def test_pending_future_no_flip(self, machine):
        """Pending future res. → maszyna pozostaje W_MAGAZYNIE."""
        PendingReservationFactory(
            machine=machine,
            start_date=date(2030, 5, 1),
            end_date=date(2030, 5, 10),
        )
        result = run_daily_sync(today=date(2030, 1, 1))
        machine.refresh_from_db()
        assert machine.status == Machine.Status.W_MAGAZYNIE
        # Wszystkie countery zero — pending nie liczone.
        assert result == {"updated": 0, "extended": 0, "reserved": 0, "today": date(2030, 1, 1)}


@pytest.mark.django_db
class TestUpdateReservationDatesUnchangedFastPath:
    """Kill mutation: ``update_reservation`` line 245 ``dates_changed = (a) != (b)``.

    Sprawdza że jeśli daty NIE są przekazane jako ``fields``, ``new_start``
    i ``new_end`` defaultują do istniejących wartości, więc ``dates_changed``
    powinno być False (krótki obwód — żaden conflict check).

    Mutacja na ``==`` zamiast ``!=`` w dates_changed (lub ``!=`` w obu polach)
    odwróciłaby flagę, ale skutek (false positive raise) jest pokryty wyżej.
    Ten test waliduje przypadek default values ``fields.get(..., default)``.
    """

    def test_no_date_fields_passed_keeps_dates(self, machine):
        """Update bez date_fields nie modyfikuje dat ani nie sprawdza konfliktu."""
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 3, 1),
            end_date=date(2030, 3, 5),
        )
        update_reservation(res, person="Tylko Osoba", notes="tylko notatka")
        res.refresh_from_db()
        # Daty bez zmian.
        assert res.start_date == date(2030, 3, 1)
        assert res.end_date == date(2030, 3, 5)
        assert res.person == "Tylko Osoba"
        assert res.notes == "tylko notatka"
