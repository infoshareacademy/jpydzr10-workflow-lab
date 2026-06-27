"""i18n acceptance tests for the reservations area.

Covers four areas that Task 1.1 locks in for the reservations app:

* **Date formatting** — dates render as ``dd.mm.yyyy`` (European format) in
  *both* ``pl`` and ``en``, because the format is forced program-wide via
  ``planer_config.formats``.
* **Status labels** — ``get_status_display`` translates under ``en`` vs ``pl``.
* **Page chrome** — a reservations page requested with the ``en`` language
  renders English chrome; with ``pl`` it renders Polish.
* **Currency** — service costs carry the ``EUR`` currency.
* **Validation messages** — model ``clean()`` errors are localized.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import formats
from django.utils.translation import override

from reservations.factories import PendingReservationFactory
from reservations.models import ConstructionSite, Reservation
from service.models import ServiceRecord

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Date formatting — European dd.mm.yyyy in both locales
# ---------------------------------------------------------------------------

_SAMPLE_DATE = datetime.date(2026, 3, 9)  # 09.03.2026 in dd.mm.yyyy


def test_date_format_is_european_under_pl():
    """A date renders as dd.mm.yyyy under the Polish locale."""
    with override("pl"):
        rendered = formats.date_format(_SAMPLE_DATE, format="SHORT_DATE_FORMAT")
    assert rendered == "09.03.2026"


def test_date_format_is_european_under_en():
    """The same date renders as dd.mm.yyyy under the English locale (forced)."""
    with override("en"):
        rendered = formats.date_format(_SAMPLE_DATE, format="SHORT_DATE_FORMAT")
    assert rendered == "09.03.2026"


def test_reservation_start_date_renders_european(machine):
    """A real reservation's start_date renders dd.mm.yyyy via date_format."""
    reservation = PendingReservationFactory(
        machine=machine,
        start_date=datetime.date(2026, 12, 1),
        end_date=datetime.date(2026, 12, 5),
    )
    with override("en"):
        rendered = formats.date_format(reservation.start_date, format="SHORT_DATE_FORMAT")
    assert rendered == "01.12.2026"


# ---------------------------------------------------------------------------
# Status labels — get_status_display translates
# ---------------------------------------------------------------------------


def test_reservation_status_display_translates_to_english(machine):
    """get_status_display returns the English msgstr under override('en')."""
    reservation = PendingReservationFactory(machine=machine, status=Reservation.Status.OCZEKUJACA)
    with override("en"):
        assert str(reservation.get_status_display()) == "Pending"


def test_reservation_status_display_polish(machine):
    """get_status_display returns the Polish label under override('pl')."""
    reservation = PendingReservationFactory(machine=machine, status=Reservation.Status.POTWIERDZONA)
    with override("pl"):
        assert str(reservation.get_status_display()) == "Potwierdzona"


def test_all_reservation_statuses_have_english_labels(machine):
    """Every reservation status label resolves to a distinct English string."""
    expected = {
        Reservation.Status.OCZEKUJACA: "Pending",
        Reservation.Status.POTWIERDZONA: "Confirmed",
        Reservation.Status.ANULOWANA: "Cancelled",
        Reservation.Status.ZAKONCZONA: "Completed",
    }
    with override("en"):
        for status, label in expected.items():
            reservation = Reservation(status=status)
            assert str(reservation.get_status_display()) == label


def test_site_status_display_translates(site):
    """ConstructionSite status label translates under override('en')."""
    site.status = ConstructionSite.Status.AKTYWNA
    with override("en"):
        assert str(site.get_status_display()) == "Active"
    with override("pl"):
        assert str(site.get_status_display()) == "Aktywna"


# ---------------------------------------------------------------------------
# Page chrome — English vs Polish via the language cookie
# ---------------------------------------------------------------------------


def test_reservation_list_renders_english_with_en_cookie(client_logged):
    """The reservation list shows English chrome with the en language cookie."""
    client_logged.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    response = client_logged.get("/rezerwacje/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Reservation list" in body
    assert "All machine reservations" in body


def test_reservation_list_renders_polish_with_pl_cookie(client_logged):
    """The reservation list shows Polish chrome with the pl language cookie."""
    client_logged.cookies[settings.LANGUAGE_COOKIE_NAME] = "pl"
    response = client_logged.get("/rezerwacje/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Lista rezerwacji" in body
    assert "Wszystkie rezerwacje maszyn" in body


def test_reservation_list_responds_to_accept_language_header(client_logged):
    """ACCEPT_LANGUAGE: en also drives English chrome (no cookie set)."""
    response = client_logged.get("/rezerwacje/", HTTP_ACCEPT_LANGUAGE="en")
    assert response.status_code == 200
    assert "Reservation list" in response.content.decode()


# ---------------------------------------------------------------------------
# Currency — EUR everywhere
# ---------------------------------------------------------------------------


def test_service_record_cost_is_eur(machine):
    """A ServiceRecord cost carries the EUR currency."""
    record = ServiceRecord.objects.create(
        machine=machine,
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=datetime.date(2026, 1, 15),
        cost=Decimal("123.45"),
    )
    assert str(record.cost.currency) == "EUR"
    assert record.cost.amount == Decimal("123.45")


def test_service_record_default_currency_is_eur(machine):
    """The MoneyField default currency is EUR even without an explicit value."""
    record = ServiceRecord.objects.create(
        machine=machine,
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=datetime.date(2026, 1, 15),
    )
    assert str(record.cost.currency) == "EUR"


# ---------------------------------------------------------------------------
# Validation messages — localized clean() errors
# ---------------------------------------------------------------------------


def test_validation_message_localized_english(machine):
    """end < start raises the English validation message under override('en')."""
    reservation = Reservation(
        machine=machine,
        start_date=datetime.date(2026, 5, 10),
        end_date=datetime.date(2026, 5, 1),
        person="Jan Kowalski",
    )
    with override("en"):
        with pytest.raises(ValidationError) as exc:
            reservation.clean()
        assert "End date must be >= start date." in exc.value.messages


def test_validation_message_localized_polish(machine):
    """end < start raises the Polish validation message under override('pl')."""
    reservation = Reservation(
        machine=machine,
        start_date=datetime.date(2026, 5, 10),
        end_date=datetime.date(2026, 5, 1),
        person="Jan Kowalski",
    )
    with override("pl"):
        with pytest.raises(ValidationError) as exc:
            reservation.clean()
        assert "Data końca musi być >= data początku." in exc.value.messages
