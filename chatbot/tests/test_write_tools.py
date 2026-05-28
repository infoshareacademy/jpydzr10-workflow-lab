"""Testy WRITE tools chatbota (Wave 14-C) — propose_* + execute_confirmed_action.

Każdy ``propose_*`` zwraca JSON proposal i NIE mutuje DB. Pełne wykonanie
przechodzi przez :func:`execute_confirmed_action` po confirmation usera.

Testy są zorganizowane w 5 sekcji — po jednej na każde write narzędzie —
plus sekcja "executor" pokrywająca defense-in-depth permission re-check.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from chatbot import tools as chatbot_tools
from chatbot.tools import (
    CancelReservationParams,
    ChangeOperatorParams,
    CreateReservationParams,
    CreateServiceRecordParams,
    SetMachineToServiceParams,
    SwapMachineParams,
    UpdateMachineInspectionDateParams,
    UpdateServiceRecordParams,
    execute_confirmed_action,
    propose_create_service_record,
    propose_update_machine_inspection_date,
    propose_update_service_record,
)
from machines.models import Machine
from reservations.models import ConstructionSite, Reservation
from service.models import ServiceRecord

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def user_full_perms(db):
    """User z PEŁNYMI write uprawnieniami dla rezerwacji + maszyn."""
    user_model = get_user_model()
    u = user_model.objects.create_user(username="full-write-tester", password="x")
    perms = [
        ("reservations", "add_reservation"),
        ("reservations", "change_reservation"),
        ("reservations", "view_reservation"),
        ("machines", "change_machine"),
        ("machines", "view_machine"),
    ]
    for app_label, codename in perms:
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        u.user_permissions.add(perm)
    # Reload to refresh permission cache.
    return user_model.objects.get(pk=u.pk)


@pytest.fixture
def user_view_only(db):
    """User z TYLKO view uprawnieniami — nie może write."""
    user_model = get_user_model()
    u = user_model.objects.create_user(username="readonly-tester", password="x")
    perms = [
        ("reservations", "view_reservation"),
        ("machines", "view_machine"),
    ]
    for app_label, codename in perms:
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        u.user_permissions.add(perm)
    return user_model.objects.get(pk=u.pk)


@pytest.fixture
def koparka_001(db):
    """Maszyna w magazynie — bazowy stan dla testów write."""
    return Machine.objects.create(
        uid="KOP-001",
        name="Koparka write test",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


@pytest.fixture
def koparka_002(db):
    """Druga maszyna — do testów swap."""
    return Machine.objects.create(
        uid="KOP-002",
        name="Koparka swap test",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


@pytest.fixture
def site_bud_007(db):
    """Budowa BUD-2026-007 — dla powiązania rezerwacji z budową."""
    return ConstructionSite.objects.create(
        project_number="BUD-2026-007",
        name="Test budowy",
        address="Test ulica 1",
        status=ConstructionSite.Status.AKTYWNA,
    )


@pytest.fixture
def reservation_pending(db, koparka_001):
    """Aktywna OCZEKUJACA rezerwacja — baza dla cancel/change/swap testów."""
    today = date.today()
    return Reservation.objects.create(
        machine=koparka_001,
        start_date=today + timedelta(days=5),
        end_date=today + timedelta(days=10),
        person="Tomek Kowalski",
        status=Reservation.Status.OCZEKUJACA,
    )


# =============================================================================
# propose_create_reservation
# =============================================================================


@pytest.mark.django_db
class TestProposeCreateReservation:
    def _params(self, machine_uid="KOP-001"):
        today = date.today()
        return CreateReservationParams(
            machine_uid=machine_uid,
            start_date=(today + timedelta(days=3)).isoformat(),
            end_date=(today + timedelta(days=8)).isoformat(),
            person="Jan Kowalski",
        )

    def test_returns_json_proposal(self, user_full_perms, koparka_001):
        result = chatbot_tools.propose_create_reservation(self._params(), user=user_full_perms)
        data = json.loads(result)
        assert data["proposed_action"] == "create_reservation"
        assert data["confirmation_required"] is True
        assert data["params"]["machine_uid"] == "KOP-001"
        assert "preview" in data
        assert "KOP-001" in data["preview"]

    def test_does_not_create_in_db(self, user_full_perms, koparka_001):
        # Sanity: liczba rezerwacji nie zmienia się po propose.
        before = Reservation.objects.count()
        chatbot_tools.propose_create_reservation(self._params(), user=user_full_perms)
        assert Reservation.objects.count() == before

    def test_refuses_without_permission(self, user_view_only, koparka_001):
        result = chatbot_tools.propose_create_reservation(self._params(), user=user_view_only)
        data = json.loads(result)
        assert "error" in data
        assert "Brak uprawnień" in data["error"]

    def test_refuses_anonymous_user(self, koparka_001):
        from django.contrib.auth.models import AnonymousUser

        result = chatbot_tools.propose_create_reservation(self._params(), user=AnonymousUser())
        data = json.loads(result)
        assert "error" in data

    def test_rejects_invalid_date_format(self, user_full_perms, koparka_001):
        """Wave 14-H Bundle H-1: Pydantic blokuje bad-date przy schema validation.

        Wcześniej walidacja była w propose_create_reservation (try/except
        date.fromisoformat); teraz pattern=r"^\\d{4}-\\d{2}-\\d{2}$" w
        CreateReservationParams blokuje przed wywołaniem narzędzia.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CreateReservationParams(
                machine_uid="KOP-001",
                start_date="bad-date",
                end_date="2026-06-10",
                person="Jan",
            )
        assert "start_date" in str(exc.value).lower()

    def test_rejects_end_before_start(self, user_full_perms, koparka_001):
        today = date.today()
        params = CreateReservationParams(
            machine_uid="KOP-001",
            start_date=(today + timedelta(days=10)).isoformat(),
            end_date=(today + timedelta(days=5)).isoformat(),
            person="Jan",
        )
        result = chatbot_tools.propose_create_reservation(params, user=user_full_perms)
        data = json.loads(result)
        assert "error" in data

    def test_rejects_dates_in_past(self, user_full_perms, koparka_001):
        params = CreateReservationParams(
            machine_uid="KOP-001",
            start_date="2020-01-01",
            end_date="2020-01-05",
            person="Jan",
        )
        result = chatbot_tools.propose_create_reservation(params, user=user_full_perms)
        data = json.loads(result)
        assert "error" in data

    def test_rejects_unknown_machine(self, user_full_perms):
        result = chatbot_tools.propose_create_reservation(
            self._params(machine_uid="GHOST-999"), user=user_full_perms
        )
        data = json.loads(result)
        assert "error" in data
        assert "GHOST-999" in data["error"]

    def test_rejects_empty_person(self, user_full_perms, koparka_001):
        today = date.today()
        params = CreateReservationParams(
            machine_uid="KOP-001",
            start_date=(today + timedelta(days=3)).isoformat(),
            end_date=(today + timedelta(days=8)).isoformat(),
            person="   ",
        )
        result = chatbot_tools.propose_create_reservation(params, user=user_full_perms)
        data = json.loads(result)
        assert "error" in data

    def test_site_lookup_by_project_number(self, user_full_perms, koparka_001, site_bud_007):
        today = date.today()
        params = CreateReservationParams(
            machine_uid="KOP-001",
            start_date=(today + timedelta(days=3)).isoformat(),
            end_date=(today + timedelta(days=8)).isoformat(),
            person="Jan Kowalski",
            site_project_number="BUD-2026-007",
        )
        result = chatbot_tools.propose_create_reservation(params, user=user_full_perms)
        data = json.loads(result)
        assert "error" not in data
        assert data["params"]["site_id"] == site_bud_007.pk

    def test_unknown_site_returns_error(self, user_full_perms, koparka_001):
        today = date.today()
        params = CreateReservationParams(
            machine_uid="KOP-001",
            start_date=(today + timedelta(days=3)).isoformat(),
            end_date=(today + timedelta(days=8)).isoformat(),
            person="Jan",
            site_project_number="BUD-GHOST-001",
        )
        result = chatbot_tools.propose_create_reservation(params, user=user_full_perms)
        data = json.loads(result)
        assert "error" in data


# =============================================================================
# propose_cancel_reservation
# =============================================================================


@pytest.mark.django_db
class TestProposeCancelReservation:
    def test_returns_json_proposal(self, user_full_perms, reservation_pending):
        params = CancelReservationParams(
            reservation_id=reservation_pending.pk,
            reason="klient_zrezygnowal",
        )
        result = chatbot_tools.propose_cancel_reservation(params, user=user_full_perms)
        data = json.loads(result)
        assert data["proposed_action"] == "cancel_reservation"
        assert data["confirmation_required"] is True
        assert data["params"]["reservation_id"] == reservation_pending.pk

    def test_does_not_modify_db(self, user_full_perms, reservation_pending):
        params = CancelReservationParams(
            reservation_id=reservation_pending.pk,
            reason="klient_zrezygnowal",
        )
        chatbot_tools.propose_cancel_reservation(params, user=user_full_perms)
        reservation_pending.refresh_from_db()
        # Status pozostaje OCZEKUJACA (propose nie wykonuje).
        assert reservation_pending.status == Reservation.Status.OCZEKUJACA

    def test_refuses_without_permission(self, user_view_only, reservation_pending):
        params = CancelReservationParams(
            reservation_id=reservation_pending.pk,
            reason="klient_zrezygnowal",
        )
        result = chatbot_tools.propose_cancel_reservation(params, user=user_view_only)
        assert "error" in json.loads(result)

    def test_rejects_unknown_reservation(self, user_full_perms):
        params = CancelReservationParams(
            reservation_id=99999,
            reason="klient_zrezygnowal",
        )
        result = chatbot_tools.propose_cancel_reservation(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_rejects_invalid_reason(self, user_full_perms, reservation_pending):
        """Wave 14-H Bundle H-1: Literal type w schema blokuje bogus reasons."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CancelReservationParams(
                reservation_id=reservation_pending.pk,
                reason="bogus_reason_xxx",
            )
        assert "reason" in str(exc.value).lower()

    def test_rejects_already_cancelled(self, user_full_perms, reservation_pending):
        reservation_pending.status = Reservation.Status.ANULOWANA
        reservation_pending.save()
        params = CancelReservationParams(
            reservation_id=reservation_pending.pk,
            reason="klient_zrezygnowal",
        )
        result = chatbot_tools.propose_cancel_reservation(params, user=user_full_perms)
        assert "error" in json.loads(result)


# =============================================================================
# propose_change_operator
# =============================================================================


@pytest.mark.django_db
class TestProposeChangeOperator:
    def test_returns_json_proposal(self, user_full_perms, reservation_pending):
        params = ChangeOperatorParams(
            reservation_id=reservation_pending.pk,
            new_person="Sven Olsen",
        )
        result = chatbot_tools.propose_change_operator(params, user=user_full_perms)
        data = json.loads(result)
        assert data["proposed_action"] == "change_operator"
        assert data["params"]["new_person"] == "Sven Olsen"

    def test_does_not_modify_db(self, user_full_perms, reservation_pending):
        params = ChangeOperatorParams(
            reservation_id=reservation_pending.pk,
            new_person="Sven Olsen",
        )
        chatbot_tools.propose_change_operator(params, user=user_full_perms)
        reservation_pending.refresh_from_db()
        assert reservation_pending.person == "Tomek Kowalski"

    def test_rejects_too_short_name(self, user_full_perms, reservation_pending):
        params = ChangeOperatorParams(
            reservation_id=reservation_pending.pk,
            new_person="X",
        )
        result = chatbot_tools.propose_change_operator(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_rejects_same_person(self, user_full_perms, reservation_pending):
        params = ChangeOperatorParams(
            reservation_id=reservation_pending.pk,
            new_person="tomek kowalski",  # case-insensitive same
        )
        result = chatbot_tools.propose_change_operator(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_refuses_without_permission(self, user_view_only, reservation_pending):
        params = ChangeOperatorParams(
            reservation_id=reservation_pending.pk,
            new_person="Sven Olsen",
        )
        result = chatbot_tools.propose_change_operator(params, user=user_view_only)
        assert "error" in json.loads(result)


# =============================================================================
# propose_swap_machine
# =============================================================================


@pytest.mark.django_db
class TestProposeSwapMachine:
    def test_returns_json_proposal(self, user_full_perms, reservation_pending, koparka_002):
        params = SwapMachineParams(
            reservation_id=reservation_pending.pk,
            new_machine_uid="KOP-002",
        )
        result = chatbot_tools.propose_swap_machine(params, user=user_full_perms)
        data = json.loads(result)
        assert data["proposed_action"] == "swap_machine"
        assert data["params"]["new_machine_uid"] == "KOP-002"

    def test_rejects_same_machine(self, user_full_perms, reservation_pending):
        params = SwapMachineParams(
            reservation_id=reservation_pending.pk,
            new_machine_uid=reservation_pending.machine.uid,
        )
        result = chatbot_tools.propose_swap_machine(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_rejects_unknown_new_machine(self, user_full_perms, reservation_pending):
        # UID format-valid (Wave 14-H Bundle H-1 pattern) ale nieistniejący.
        params = SwapMachineParams(
            reservation_id=reservation_pending.pk,
            new_machine_uid="GHOST-999",
        )
        result = chatbot_tools.propose_swap_machine(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_rejects_retired_machine(self, user_full_perms, reservation_pending, koparka_002):
        koparka_002.status = Machine.Status.WYCOFANA
        koparka_002.save()
        params = SwapMachineParams(
            reservation_id=reservation_pending.pk,
            new_machine_uid="KOP-002",
        )
        result = chatbot_tools.propose_swap_machine(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_swap_machine_requires_both_change_AND_add_reservation_perms(  # noqa: N802
        self, db, reservation_pending, koparka_002
    ):
        """Wave 14-H Bundle H-4: swap_machine wymaga OBOIM permissions.

        User z TYLKO change_reservation (bez add_reservation) NIE może
        wykonać swap, bo swap tworzy nową rezerwację.
        """
        user_model = get_user_model()
        user_change_only = user_model.objects.create_user(username="swap-perm-test", password="x")
        # TYLKO change, brak add → swap powinien odmówić.
        user_change_only.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="reservations", codename="change_reservation"
            )
        )
        user_change_only.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="reservations", codename="view_reservation"
            )
        )
        user_change_only = user_model.objects.get(pk=user_change_only.pk)

        params = SwapMachineParams(
            reservation_id=reservation_pending.pk,
            new_machine_uid="KOP-002",
        )
        result = chatbot_tools.propose_swap_machine(params, user=user_change_only)
        data = json.loads(result)
        assert "error" in data
        assert "Brak uprawnień" in data["error"]
        # Komunikat zawiera nazwę brakującego perm.
        assert "add_reservation" in data["error"]

    def test_swap_machine_executor_also_requires_both_perms(
        self, db, reservation_pending, koparka_002
    ):
        """Defense-in-depth: executor blokuje swap nawet jeśli propose przeszedłby.

        Symulujemy że user MIAŁ oba perms przy propose ale stracił add_reservation
        przed confirm — executor powinien znów sprawdzić i odmówić.
        """
        user_model = get_user_model()
        user_change_only = user_model.objects.create_user(username="swap-exec-test", password="x")
        user_change_only.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="reservations", codename="change_reservation"
            )
        )
        user_change_only = user_model.objects.get(pk=user_change_only.pk)

        params = {
            "reservation_id": reservation_pending.pk,
            "new_machine_uid": koparka_002.uid,
            "new_machine_id": koparka_002.pk,
            "reason": "test",
        }
        result = execute_confirmed_action("swap_machine", params, user=user_change_only)
        assert "Brak uprawnień" in result
        assert "add_reservation" in result
        # Rezerwacja nie zmieniona.
        reservation_pending.refresh_from_db()
        assert reservation_pending.machine_id != koparka_002.pk


# =============================================================================
# propose_set_machine_to_service
# =============================================================================


@pytest.mark.django_db
class TestProposeSetMachineToService:
    def test_returns_json_proposal(self, user_full_perms, koparka_001):
        params = SetMachineToServiceParams(machine_uid="KOP-001")
        result = chatbot_tools.propose_set_machine_to_service(params, user=user_full_perms)
        data = json.loads(result)
        assert data["proposed_action"] == "set_machine_to_service"
        assert data["params"]["machine_uid"] == "KOP-001"

    def test_does_not_modify_db(self, user_full_perms, koparka_001):
        params = SetMachineToServiceParams(machine_uid="KOP-001")
        chatbot_tools.propose_set_machine_to_service(params, user=user_full_perms)
        koparka_001.refresh_from_db()
        assert koparka_001.status == Machine.Status.W_MAGAZYNIE

    def test_rejects_machine_already_in_service(self, user_full_perms, koparka_001):
        koparka_001.status = Machine.Status.W_SERWISIE
        koparka_001.save()
        params = SetMachineToServiceParams(machine_uid="KOP-001")
        result = chatbot_tools.propose_set_machine_to_service(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_rejects_machine_on_site(self, user_full_perms, koparka_001):
        koparka_001.status = Machine.Status.NA_BUDOWIE
        koparka_001.save()
        params = SetMachineToServiceParams(machine_uid="KOP-001")
        result = chatbot_tools.propose_set_machine_to_service(params, user=user_full_perms)
        assert "error" in json.loads(result)

    def test_refuses_without_permission(self, user_view_only, koparka_001):
        params = SetMachineToServiceParams(machine_uid="KOP-001")
        result = chatbot_tools.propose_set_machine_to_service(params, user=user_view_only)
        assert "error" in json.loads(result)


# =============================================================================
# execute_confirmed_action — defense-in-depth permission re-check
# =============================================================================


@pytest.mark.django_db
class TestExecuteConfirmedAction:
    def test_create_reservation_writes_db(self, user_full_perms, koparka_001):
        today = date.today()
        # Wave 14-H Bundle M-1: chatbot wymaga responsible_person + address.
        params = {
            "machine_id": koparka_001.pk,
            "machine_uid": koparka_001.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan Kowalski",
            "address": "ul. Budowlana 1, 00-001 Warszawa",
            "notes": "",
            "responsible_person": "Anna Kierownik",
        }
        result = execute_confirmed_action("create_reservation", params, user=user_full_perms)
        assert "utworzona" in result.lower()
        assert Reservation.objects.filter(machine=koparka_001).count() == 1

    def test_create_reservation_rejected_without_responsible_person(
        self, user_full_perms, koparka_001
    ):
        """Wave 14-H Bundle M-1: service blokuje create bez responsible_person."""
        today = date.today()
        params = {
            "machine_id": koparka_001.pk,
            "machine_uid": koparka_001.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "ul. Budowlana 1, 00-001 Warszawa",
            "notes": "",
            # responsible_person celowo brak → service powinien odmówić.
        }
        result = execute_confirmed_action("create_reservation", params, user=user_full_perms)
        assert "Nie udało się" in result or "wymagana" in result.lower()
        assert Reservation.objects.filter(machine=koparka_001).count() == 0

    def test_create_reservation_rejected_without_address(self, user_full_perms, koparka_001):
        """Wave 14-H Bundle M-1: service blokuje create bez address."""
        today = date.today()
        params = {
            "machine_id": koparka_001.pk,
            "machine_uid": koparka_001.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan",
            "address": "",  # celowo puste
            "notes": "",
            "responsible_person": "Anna Kierownik",
        }
        result = execute_confirmed_action("create_reservation", params, user=user_full_perms)
        assert "Nie udało się" in result or "wymagany" in result.lower()
        assert Reservation.objects.filter(machine=koparka_001).count() == 0

    def test_create_reservation_blocked_without_permission(self, user_view_only, koparka_001):
        today = date.today()
        params = {
            "machine_id": koparka_001.pk,
            "machine_uid": koparka_001.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=3)).isoformat(),
            "end_date": (today + timedelta(days=8)).isoformat(),
            "person": "Jan Kowalski",
            "address": "",
            "notes": "",
        }
        result = execute_confirmed_action("create_reservation", params, user=user_view_only)
        assert "Brak uprawnień" in result
        assert Reservation.objects.filter(machine=koparka_001).count() == 0

    def test_cancel_reservation_writes_status(self, user_full_perms, reservation_pending):
        params = {
            "reservation_id": reservation_pending.pk,
            "reason": "klient_zrezygnowal",
            "note": "",
        }
        result = execute_confirmed_action("cancel_reservation", params, user=user_full_perms)
        assert "anulowana" in result.lower()
        reservation_pending.refresh_from_db()
        assert reservation_pending.status == Reservation.Status.ANULOWANA

    def test_change_operator_writes_person(self, user_full_perms, reservation_pending):
        params = {
            "reservation_id": reservation_pending.pk,
            "new_person": "Sven Olsen",
        }
        result = execute_confirmed_action("change_operator", params, user=user_full_perms)
        assert "Sven Olsen" in result
        reservation_pending.refresh_from_db()
        assert reservation_pending.person == "Sven Olsen"

    def test_set_machine_to_service_writes_status(self, user_full_perms, koparka_001):
        params = {"machine_id": koparka_001.pk, "machine_uid": koparka_001.uid}
        result = execute_confirmed_action("set_machine_to_service", params, user=user_full_perms)
        assert "serwisu" in result.lower()
        koparka_001.refresh_from_db()
        assert koparka_001.status == Machine.Status.W_SERWISIE

    def test_blocks_inactive_user(self, user_full_perms, koparka_001):
        user_full_perms.is_active = False
        user_full_perms.save()
        params = {"machine_id": koparka_001.pk, "machine_uid": koparka_001.uid}
        result = execute_confirmed_action("set_machine_to_service", params, user=user_full_perms)
        assert "nieaktywne" in result.lower()
        koparka_001.refresh_from_db()
        assert koparka_001.status == Machine.Status.W_MAGAZYNIE

    def test_unknown_action_returns_friendly_error(self, user_full_perms):
        result = execute_confirmed_action("bogus_action", {}, user=user_full_perms)
        assert "Nieznana akcja" in result

    def test_validation_error_in_executor_returns_polish_message(
        self, user_full_perms, koparka_001
    ):
        # Tworzymy konflikt — istniejąca rezerwacja blokuje nowy create.
        today = date.today()
        Reservation.objects.create(
            machine=koparka_001,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=8),
            person="Already booked",
            status=Reservation.Status.POTWIERDZONA,
        )
        params = {
            "machine_id": koparka_001.pk,
            "machine_uid": koparka_001.uid,
            "site_id": None,
            "start_date": (today + timedelta(days=4)).isoformat(),
            "end_date": (today + timedelta(days=6)).isoformat(),
            "person": "Konflikt",
            "address": "",
            "notes": "",
        }
        result = execute_confirmed_action("create_reservation", params, user=user_full_perms)
        # Polski komunikat z service layer + brak wycieku class name.
        assert "Nie udało się" in result
        assert "ValidationError" not in result


# =============================================================================
# Wave 14-H Bundle H-1 — Pydantic schema constraints (DoS prevention)
# =============================================================================


class TestPydanticSchemaConstraints:
    """Pydantic ValidationError must reject oversize / malformed args."""

    def test_create_reservation_machine_uid_too_long_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CreateReservationParams(
                machine_uid="A" * 100,  # > 20 chars
                start_date="2026-06-01",
                end_date="2026-06-05",
                person="Jan",
            )
        assert "machine_uid" in str(exc.value).lower()

    def test_create_reservation_machine_uid_invalid_format_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CreateReservationParams(
                machine_uid="INVALID FORMAT",  # no hyphen + spaces
                start_date="2026-06-01",
                end_date="2026-06-05",
                person="Jan",
            )
        assert "machine_uid" in str(exc.value).lower()

    def test_create_reservation_person_too_long_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CreateReservationParams(
                machine_uid="KOP-001",
                start_date="2026-06-01",
                end_date="2026-06-05",
                person="A" * 200,  # > 100 chars
            )
        assert "person" in str(exc.value).lower()

    def test_create_reservation_notes_too_long_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CreateReservationParams(
                machine_uid="KOP-001",
                start_date="2026-06-01",
                end_date="2026-06-05",
                person="Jan",
                notes="A" * 1000,  # > 500 chars
            )
        assert "notes" in str(exc.value).lower()

    def test_create_reservation_invalid_date_format_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CreateReservationParams(
                machine_uid="KOP-001",
                start_date="01.06.2026",  # DD.MM.YYYY — not ISO
                end_date="2026-06-05",
                person="Jan",
            )

    def test_create_reservation_address_too_long_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CreateReservationParams(
                machine_uid="KOP-001",
                start_date="2026-06-01",
                end_date="2026-06-05",
                person="Jan",
                address="A" * 500,  # > 300
            )
        assert "address" in str(exc.value).lower()

    def test_create_reservation_site_project_number_invalid_format(self):
        from pydantic import ValidationError

        # site_project_number must match BUD-RRRR-NNN when given.
        # Empty default OK; "FOO-2026-001" is wrong prefix → rejected only if pattern enforced.
        # Bundle H-1 didn't add pattern for site_project_number (it's optional / free-text-ish),
        # but max_length must apply.
        with pytest.raises(ValidationError) as exc:
            CreateReservationParams(
                machine_uid="KOP-001",
                start_date="2026-06-01",
                end_date="2026-06-05",
                person="Jan",
                site_project_number="A" * 100,  # > 20
            )
        assert "site_project_number" in str(exc.value).lower()

    def test_cancel_reservation_id_zero_rejected(self):
        from pydantic import ValidationError

        # gt=0 → 0 rejected, 1 OK
        with pytest.raises(ValidationError):
            CancelReservationParams(reservation_id=0, reason="inne")
        # negative
        with pytest.raises(ValidationError):
            CancelReservationParams(reservation_id=-5, reason="inne")
        # huge
        with pytest.raises(ValidationError):
            CancelReservationParams(reservation_id=10**12, reason="inne")
        # OK
        ok = CancelReservationParams(reservation_id=42, reason="inne")
        assert ok.reservation_id == 42

    def test_cancel_reservation_invalid_reason_rejected(self):
        """Literal type — only allowed strings work."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            CancelReservationParams(reservation_id=1, reason="random_text_attack")
        assert "reason" in str(exc.value).lower()

    def test_change_operator_new_person_too_long_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            ChangeOperatorParams(reservation_id=1, new_person="A" * 200)
        assert "new_person" in str(exc.value).lower()

    def test_swap_machine_new_uid_invalid_format_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            SwapMachineParams(reservation_id=1, new_machine_uid="not a uid")
        assert "new_machine_uid" in str(exc.value).lower()

    def test_swap_machine_reason_too_long_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            SwapMachineParams(reservation_id=1, new_machine_uid="KOP-002", reason="A" * 1000)
        assert "reason" in str(exc.value).lower()

    def test_set_machine_to_service_invalid_uid_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SetMachineToServiceParams(machine_uid="INVALID")

    def test_create_reservation_valid_input_accepts(self):
        """Sanity: well-formed input passes."""
        params = CreateReservationParams(
            machine_uid="KOP-001",
            start_date="2026-06-01",
            end_date="2026-06-05",
            person="Jan Kowalski",
            site_project_number="BUD-2026-001",
            address="ul. Testowa 1",
            notes="Pilne",
            responsible_person="Anna Nowak",
        )
        assert params.machine_uid == "KOP-001"
        assert params.responsible_person == "Anna Nowak"


# =============================================================================
# Faza A — service write tools (przegląd / naprawa / przesunięcie daty)
# =============================================================================


@pytest.fixture
def user_service_perms(db):
    """User z PEŁNYMI uprawnieniami serwisowymi + machine change (dla
    update_machine_inspection_date)."""
    user_model = get_user_model()
    u = user_model.objects.create_user(username="service-write-tester", password="x")
    perms = [
        ("service", "add_servicerecord"),
        ("service", "change_servicerecord"),
        ("service", "view_servicerecord"),
        ("machines", "change_machine"),
        ("machines", "view_machine"),
    ]
    for app_label, codename in perms:
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        u.user_permissions.add(perm)
    return user_model.objects.get(pk=u.pk)


@pytest.mark.django_db
class TestProposeCreateServiceRecord:
    """Wpis serwisowy (przegląd lub naprawa) z opcjonalnym kosztem."""

    def _params(self, **overrides):
        defaults = {
            "machine_uid": "KOP-001",
            "record_type": "naprawa",
            "performed_date": date.today().isoformat(),
            "performed_by": "Jan Serwisant",
            "description": "Wymiana baterii",
            "cost": 308.0,
        }
        defaults.update(overrides)
        return CreateServiceRecordParams(**defaults)

    def test_returns_proposal_json_with_action(self, user_service_perms, koparka_001):
        result = propose_create_service_record(self._params(), user=user_service_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "create_service_record"
        assert payload["confirmation_required"] is True
        assert payload["params"]["machine_uid"] == "KOP-001"
        assert payload["params"]["record_type"] == "naprawa"
        assert payload["params"]["cost"] == 308.0
        assert "Wymiana baterii" in payload["preview"]

    def test_inspection_type_preview_mentions_auto_next_date(
        self, user_service_perms, koparka_001
    ):
        """Dla typów przeglad_* preview MUSI wspomnieć o auto-przesunięciu daty."""
        result = propose_create_service_record(
            self._params(record_type="przegląd_kwartalny", cost=120.0),
            user=user_service_perms,
        )
        payload = json.loads(result)
        assert "3 mc" in payload["preview"]

    def test_naprawa_preview_does_not_mention_inspection_shift(
        self, user_service_perms, koparka_001
    ):
        """Dla naprawy preview NIE wspomina o przesunięciu daty przeglądu."""
        result = propose_create_service_record(self._params(), user=user_service_perms)
        payload = json.loads(result)
        assert "mc od" not in payload["preview"]

    def test_rejects_user_without_perm(self, user_view_only, koparka_001):
        result = propose_create_service_record(self._params(), user=user_view_only)
        payload = json.loads(result)
        assert "error" in payload
        assert "uprawnień" in payload["error"]

    def test_rejects_nonexistent_machine(self, user_service_perms):
        result = propose_create_service_record(
            self._params(machine_uid="ZZZ-999"), user=user_service_perms
        )
        payload = json.loads(result)
        assert "error" in payload
        assert "ZZZ-999" in payload["error"]

    def test_rejects_future_performed_date(self, user_service_perms, koparka_001):
        future = (date.today() + timedelta(days=5)).isoformat()
        result = propose_create_service_record(
            self._params(performed_date=future), user=user_service_perms
        )
        payload = json.loads(result)
        assert "error" in payload
        assert "przyszłości" in payload["error"]

    def test_zero_cost_renders_bez_kosztu(self, user_service_perms, koparka_001):
        result = propose_create_service_record(
            self._params(cost=0.0), user=user_service_perms
        )
        payload = json.loads(result)
        assert "bez kosztu" in payload["preview"]


@pytest.mark.django_db
class TestProposeUpdateServiceRecord:
    """Korekta istniejącego wpisu serwisowego."""

    @pytest.fixture
    def existing_record(self, koparka_001):
        from decimal import Decimal

        return ServiceRecord.objects.create(
            machine=koparka_001,
            record_type=ServiceRecord.RecordType.NAPRAWA,
            performed_date=date.today() - timedelta(days=2),
            performed_by="Tomek",
            description="Stary opis",
            cost=Decimal("100.00"),
        )

    def test_proposes_cost_change(self, user_service_perms, existing_record):
        params = UpdateServiceRecordParams(record_id=existing_record.pk, cost=350.0)
        result = propose_update_service_record(params, user=user_service_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "update_service_record"
        assert "350.00 EUR" in payload["preview"]

    def test_rejects_when_no_changes(self, user_service_perms, existing_record):
        """Przekazanie pustych zmian → error (avoid no-op write)."""
        params = UpdateServiceRecordParams(record_id=existing_record.pk)
        result = propose_update_service_record(params, user=user_service_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "Brak zmian" in payload["error"]

    def test_rejects_nonexistent_record(self, user_service_perms):
        params = UpdateServiceRecordParams(record_id=99999, cost=200.0)
        result = propose_update_service_record(params, user=user_service_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "99999" in payload["error"]

    def test_rejects_user_without_perm(self, user_view_only, existing_record):
        params = UpdateServiceRecordParams(record_id=existing_record.pk, cost=200.0)
        result = propose_update_service_record(params, user=user_view_only)
        payload = json.loads(result)
        assert "error" in payload


@pytest.mark.django_db
class TestProposeUpdateMachineInspectionDate:
    """Samo przesunięcie Machine.inspection_date bez tworzenia ServiceRecord."""

    def test_proposes_new_date(self, user_service_perms, koparka_001):
        koparka_001.inspection_date = date.today() + timedelta(days=30)
        koparka_001.save(update_fields=["inspection_date", "updated_at"])
        new_date = (date.today() + timedelta(days=90)).isoformat()
        params = UpdateMachineInspectionDateParams(
            machine_uid="KOP-001", next_inspection_date=new_date
        )
        result = propose_update_machine_inspection_date(params, user=user_service_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "update_machine_inspection_date"
        assert new_date in payload["preview"]

    def test_warns_when_new_date_in_past(self, user_service_perms, koparka_001):
        past = (date.today() - timedelta(days=5)).isoformat()
        params = UpdateMachineInspectionDateParams(
            machine_uid="KOP-001", next_inspection_date=past
        )
        result = propose_update_machine_inspection_date(params, user=user_service_perms)
        payload = json.loads(result)
        assert "przeszłości" in payload["preview"]

    def test_rejects_user_without_perm(self, user_view_only, koparka_001):
        params = UpdateMachineInspectionDateParams(
            machine_uid="KOP-001", next_inspection_date="2026-12-01"
        )
        result = propose_update_machine_inspection_date(params, user=user_view_only)
        payload = json.loads(result)
        assert "error" in payload


@pytest.mark.django_db
class TestExecuteServiceActions:
    """Pełna ścieżka: execute_confirmed_action → faktyczna mutacja DB."""

    def test_execute_create_service_record(self, user_service_perms, koparka_001):
        params = {
            "machine_id": koparka_001.pk,
            "machine_uid": koparka_001.uid,
            "record_type": "naprawa",
            "performed_date": date.today().isoformat(),
            "performed_by": "Jan Serwisant",
            "description": "Wymiana baterii",
            "cost": 308.0,
        }
        result = execute_confirmed_action(
            "create_service_record", params, user=user_service_perms
        )
        assert "Wpis serwisowy" in result
        assert "KOP-001" in result
        # DB stan się zmienił.
        assert ServiceRecord.objects.filter(machine=koparka_001).count() == 1
        record = ServiceRecord.objects.get(machine=koparka_001)
        assert record.record_type == "naprawa"
        assert record.description == "Wymiana baterii"
        assert float(record.cost) == 308.0

    def test_execute_create_inspection_bumps_machine_date(
        self, user_service_perms, koparka_001
    ):
        """Przegląd kwartalny → Machine.inspection_date = performed + 3 mc."""
        today = date.today()
        params = {
            "machine_id": koparka_001.pk,
            "machine_uid": koparka_001.uid,
            "record_type": "przegląd_kwartalny",
            "performed_date": today.isoformat(),
            "performed_by": "",
            "description": "",
            "cost": 120.0,
        }
        execute_confirmed_action("create_service_record", params, user=user_service_perms)
        koparka_001.refresh_from_db()
        # +3 mc → liczone przez relativedelta w service warstwie.
        expected_min = today + timedelta(days=85)  # ~3 mc
        expected_max = today + timedelta(days=95)
        assert koparka_001.inspection_date is not None
        assert expected_min <= koparka_001.inspection_date <= expected_max

    def test_execute_update_service_record(self, user_service_perms, koparka_001):
        from decimal import Decimal

        record = ServiceRecord.objects.create(
            machine=koparka_001,
            record_type=ServiceRecord.RecordType.NAPRAWA,
            performed_date=date.today() - timedelta(days=1),
            performed_by="Tomek",
            description="Stary opis",
            cost=Decimal("100.00"),
        )
        result = execute_confirmed_action(
            "update_service_record",
            {"record_id": record.pk, "cost": 350.0, "description": "Nowy opis"},
            user=user_service_perms,
        )
        assert "zaktualizowany" in result
        record.refresh_from_db()
        assert float(record.cost) == 350.0
        assert record.description == "Nowy opis"

    def test_execute_update_machine_inspection_date(self, user_service_perms, koparka_001):
        new_date = (date.today() + timedelta(days=60)).isoformat()
        result = execute_confirmed_action(
            "update_machine_inspection_date",
            {
                "machine_id": koparka_001.pk,
                "machine_uid": koparka_001.uid,
                "next_inspection_date": new_date,
            },
            user=user_service_perms,
        )
        assert "zaktualizowana" in result
        koparka_001.refresh_from_db()
        assert koparka_001.inspection_date == date.fromisoformat(new_date)

    def test_execute_rejects_user_without_perm(self, user_view_only, koparka_001):
        result = execute_confirmed_action(
            "create_service_record",
            {
                "machine_id": koparka_001.pk,
                "machine_uid": koparka_001.uid,
                "record_type": "naprawa",
                "performed_date": date.today().isoformat(),
                "cost": 50.0,
            },
            user=user_view_only,
        )
        assert "Brak uprawnień" in result
