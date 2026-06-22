"""Unit tests for the :mod:`reservations.models` module.

Covers:

* Field defaults / verbose names / ordering.
* Project number validator (BUD-RRRR-NNN).
* ``Reservation.clean`` cross-field validation.
* Convenience properties (``is_open``, ``duration_days``, …).
* String representations.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from reservations.models import ConstructionSite, Reservation

# =============================================================================
# CONSTRUCTION SITE
# =============================================================================


class TestConstructionSiteValidators:
    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "valid_number",
        [
            # Legacy format BUD-RRRR-NNN (zachowany dla wstecznej kompatybilnosci)
            "BUD-2026-001",
            "BUD-9999-999",
            "BUD-0000-000",
            # Nowy format 10YYNNNNN (preferowany od 2026-05-31)
            "10260000001",
            "10269999999",
            "10300000042",
        ],
    )
    def test_accepts_valid_project_number(self, valid_number):
        site = ConstructionSite(
            project_number=valid_number,
            name="Demo",
            address="Adres demo 1",
        )
        site.full_clean()  # no exception

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "bad_number",
        [
            "BUD-26-001",  # rok < 4 cyfr
            "BUD-2026-1",  # numer < 3 cyfr
            "BUD-2026-0001",  # numer > 3 cyfr
            "bud-2026-001",  # lowercase prefix
            "BUD_2026_001",  # underscores
            "123456789",  # plain 9-digit numeric (rejected per project decision)
            "",
            "BUD-2026-001-x",  # suffix
        ],
    )
    def test_rejects_invalid_project_number(self, bad_number):
        site = ConstructionSite(
            project_number=bad_number,
            name="Demo",
            address="Adres demo 1",
        )
        with pytest.raises(ValidationError):
            site.full_clean()

    @pytest.mark.django_db
    def test_str_representation(self):
        site = ConstructionSite(project_number="BUD-2026-007", name="Budowa testowa")
        site_str = str(site)
        assert "BUD-2026-007" in site_str
        assert "Budowa testowa" in site_str

    @pytest.mark.django_db
    def test_clean_rejects_end_before_start(self):
        site = ConstructionSite(
            project_number="BUD-2026-002",
            name="Demo",
            address="Adres",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 1),
        )
        with pytest.raises(ValidationError):
            site.full_clean()


class TestConstructionSiteDefaults:
    @pytest.mark.django_db
    def test_default_status_is_aktywna(self):
        site = ConstructionSite.objects.create(
            project_number="BUD-2026-003",
            name="Demo",
            address="Adres",
        )
        assert site.status == ConstructionSite.Status.AKTYWNA
        assert site.is_active is True


# =============================================================================
# RESERVATION
# =============================================================================


class TestReservationDefaults:
    @pytest.mark.django_db
    def test_default_status_is_oczekujaca(self, machine):
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="Jan Kowalski",
        )
        assert res.status == Reservation.Status.OCZEKUJACA
        assert res.is_open is True

    @pytest.mark.django_db
    def test_duration_days_inclusive(self, machine):
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 1),
            person="X",
        )
        assert res.duration_days == 1
        res.end_date = date(2030, 1, 5)
        assert res.duration_days == 5

    @pytest.mark.django_db
    def test_title_uses_uid(self, machine):
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="Anna",
        )
        assert machine.uid in res.title
        assert "Anna" in res.title


class TestReservationValidation:
    @pytest.mark.django_db
    def test_clean_rejects_end_before_start(self, machine):
        res = Reservation(
            machine=machine,
            start_date=date(2030, 6, 10),
            end_date=date(2030, 6, 1),
            person="X",
        )
        with pytest.raises(ValidationError):
            res.full_clean()

    @pytest.mark.django_db
    def test_str_includes_machine_uid_and_dates(self, machine):
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="Anna",
        )
        out = str(res)
        assert machine.uid in out
        assert "2030-01-01" in out
        assert "Anna" in out


class TestReservationIsOpen:
    """Ensures only pending/confirmed count as "open" for status flows."""

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (Reservation.Status.OCZEKUJACA, True),
            (Reservation.Status.POTWIERDZONA, True),
            (Reservation.Status.ANULOWANA, False),
            (Reservation.Status.ZAKONCZONA, False),
        ],
    )
    def test_is_open_matrix(self, machine, status, expected):
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="X",
            status=status,
        )
        assert res.is_open is expected


class TestReservationStatusFlags:
    """Pokrycie is_pending / is_confirmed / is_closed (F13-A regression fix).

    Każda właściwość ma jednolitą semantykę: True dla zgodnego stanu(-ów),
    False dla pozostałych — co czyni je idealnym kandydatem na matrix test.
    """

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (Reservation.Status.OCZEKUJACA, True),
            (Reservation.Status.POTWIERDZONA, False),
            (Reservation.Status.ZAKONCZONA, False),
            (Reservation.Status.ANULOWANA, False),
        ],
    )
    def test_is_pending_matrix(self, machine, status, expected):
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="X",
            status=status,
        )
        assert res.is_pending is expected

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (Reservation.Status.OCZEKUJACA, False),
            (Reservation.Status.POTWIERDZONA, True),
            (Reservation.Status.ZAKONCZONA, False),
            (Reservation.Status.ANULOWANA, False),
        ],
    )
    def test_is_confirmed_matrix(self, machine, status, expected):
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="X",
            status=status,
        )
        assert res.is_confirmed is expected

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (Reservation.Status.OCZEKUJACA, False),
            (Reservation.Status.POTWIERDZONA, False),
            (Reservation.Status.ZAKONCZONA, True),
            (Reservation.Status.ANULOWANA, True),
        ],
    )
    def test_is_closed_matrix(self, machine, status, expected):
        """is_closed pokrywa stany terminalne (ZAKONCZONA + ANULOWANA)."""
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="X",
            status=status,
        )
        assert res.is_closed is expected


# =============================================================================
# WAVE 14-A BUNDLE 4 — responsible_person field
# =============================================================================


class TestReservationResponsiblePerson:
    """Wave 14-A Bundle 4 — `responsible_person` field (kierownik/brygadzista).

    Pole rozdziela `person` (kto wpisuje rezerwacje w biurze) od osoby
    odpowiedzialnej fizycznie za maszyne na budowie. Model trzyma blank=True
    + default='' dla backwards-compat z M1 fixtures; enforcement na poziomie
    formularza (zob. test_forms.TestReservationForm.test_responsible_person_*).
    """

    @pytest.mark.django_db
    def test_responsible_person_default_blank(self, machine):
        """Default empty string -- backward-compat z legacy data."""
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="Anna",
        )
        # No exception raised, blank='' jest legalny w modelu.
        assert res.responsible_person == ""

    @pytest.mark.django_db
    def test_responsible_person_stored(self, machine):
        """Persist + readback wartosci kierownika."""
        res = Reservation.objects.create(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="Anna Biuro",
            responsible_person="Brygadzista Marek",
        )
        res.refresh_from_db()
        assert res.responsible_person == "Brygadzista Marek"

    @pytest.mark.django_db
    def test_responsible_person_max_length(self, machine):
        """100-znakowy limit (full_clean rzuca dla overflow)."""
        too_long = "X" * 101
        res = Reservation(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
            person="Anna",
            responsible_person=too_long,
        )
        with pytest.raises(ValidationError):
            res.full_clean()
