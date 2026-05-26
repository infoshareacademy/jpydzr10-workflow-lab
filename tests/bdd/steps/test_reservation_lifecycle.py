"""Step implementations for ``reservation_lifecycle.feature``.

Pokrywa lukę C3-x z F7-B audytu — BDD scenariusze dla 3 kluczowych transitions
(confirm / cancel / illegal block) + edit dat. Unit testy w
``reservations/tests/test_services_transitions.py`` pokrywają logikę,
ale brakowało Gherkin opisu user-journey "magazynier potwierdza".

Konwencja:

* Status w Gherkin podajemy CAPS (``OCZEKUJACA``), w modelu to lowercase
  enum (``oczekująca``) — mapping w :data:`_STATUS_MAP`.
* Operacje wołamy bezpośrednio przez serwis (``confirm_reservation`` etc.)
  zamiast przez widoki — testujemy logikę domenową, nie HTTP routing.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from pytest_bdd import given, parsers, scenarios, then, when

from machines.factories import MachineFactory
from reservations.factories import ConstructionSiteFactory, ReservationFactory
from reservations.models import Reservation
from reservations.services import (
    cancel_reservation,
    confirm_reservation,
    update_reservation,
)

scenarios("../features/reservation_lifecycle.feature")


# Mapping CAPS-Gherkin → enum value (lowercase, zgodne z model.Status.choices).
_STATUS_MAP = {
    "OCZEKUJACA": Reservation.Status.OCZEKUJACA,
    "POTWIERDZONA": Reservation.Status.POTWIERDZONA,
    "ANULOWANA": Reservation.Status.ANULOWANA,
    "ZAKONCZONA": Reservation.Status.ZAKONCZONA,
}


# ----------------------------------------------------------------------------
# GIVEN — seed
# ----------------------------------------------------------------------------


@given(
    parsers.parse('rezerwację w statusie "{status_caps}"'),
    target_fixture="reservation",
)
def given_reservation_with_status(status_caps: str) -> Reservation:
    """Seeduje rezerwację z danym statusem (mapping CAPS → enum)."""
    status = _STATUS_MAP[status_caps]
    machine = MachineFactory(uid="BDD-LC-1")
    site = ConstructionSiteFactory(project_number="BUD-2026-LC1")
    today = date(2026, 6, 1)
    return ReservationFactory(
        machine=machine,
        site=site,
        status=status,
        start_date=today + timedelta(days=5),
        end_date=today + timedelta(days=10),
    )


# ----------------------------------------------------------------------------
# WHEN — action
# ----------------------------------------------------------------------------


@when("magazynier potwierdza rezerwację")
def when_confirm(reservation, context: dict):
    """Happy path — confirm wywołane przez serwis."""
    context["result"] = confirm_reservation(reservation)


@when("magazynier anuluje rezerwację")
def when_cancel(reservation, context: dict):
    """Happy path — cancel wywołane przez serwis.

    B-2: domyślny reason="klient_zrezygnowal" — BDD step nie testuje
    walidacji reason (to robią unit testy), tylko transition.
    """
    context["result"] = cancel_reservation(reservation, reason="klient_zrezygnowal")


@when("magazynier próbuje potwierdzić rezerwację")
def when_try_confirm(reservation, context: dict):
    """Nielegalne przejście — łapiemy ValidationError do contextu."""
    try:
        context["result"] = confirm_reservation(reservation)
    except ValidationError as exc:
        context["error"] = exc


@when(parsers.parse('magazynier zmienia datę końca rezerwacji na "{new_end}"'))
def when_update_end_date(reservation, new_end: str, context: dict):
    """Edit dates — wywołane przez ``update_reservation`` (service layer)."""
    context["result"] = update_reservation(
        reservation,
        end_date=date.fromisoformat(new_end),
    )


# ----------------------------------------------------------------------------
# THEN — assertion
# ----------------------------------------------------------------------------


@then(parsers.parse('status rezerwacji to "{status_caps}"'))
def then_status(reservation, status_caps: str):
    """Sprawdza status po refresh_from_db — service zwraca locked row, ale
    z perspektywy domeny ważne jest co jest w bazie."""
    reservation.refresh_from_db()
    assert reservation.status == _STATUS_MAP[status_caps], (
        f"Spodziewano {status_caps} ({_STATUS_MAP[status_caps]!r}), "
        f"otrzymano {reservation.status!r}"
    )


@then("operacja kończy się błędem walidacji")
def then_validation_error(context: dict):
    """Nielegalna transition — context["error"] musi być ValidationError."""
    assert "error" in context, "Spodziewano ValidationError, ale operacja przeszła"
    assert isinstance(context["error"], ValidationError)


@then(parsers.parse('rezerwacja zostaje zapisana z nową datą końca "{expected_end}"'))
def then_end_date_updated(reservation, expected_end: str):
    reservation.refresh_from_db()
    assert reservation.end_date == date.fromisoformat(expected_end)


# Auto-mark — DB-touching + integration suite.
pytestmark = [pytest.mark.integration, pytest.mark.django_db]
