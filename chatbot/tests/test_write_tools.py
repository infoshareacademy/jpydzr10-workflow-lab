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
    AnonymizeEmployeeParams,
    CancelReservationParams,
    ChangeOperatorParams,
    CloseRepairMachineParams,
    CompleteReservationParams,
    ConfirmReservationParams,
    CreateMachineParams,
    CreateReservationParams,
    CreateServiceRecordParams,
    CreateSiteParams,
    DeleteSiteParams,
    ReportBreakdownParams,
    RetireMachineParams,
    ReturnMachineParams,
    SetMachineToServiceParams,
    SwapMachineParams,
    TerminateEmployeeParams,
    UpdateMachineInspectionDateParams,
    UpdateMachineParams,
    UpdateReservationParams,
    UpdateServiceRecordParams,
    UpdateSiteParams,
    execute_confirmed_action,
    propose_anonymize_employee,
    propose_close_repair_machine,
    propose_complete_reservation,
    propose_confirm_reservation,
    propose_create_machine,
    propose_create_service_record,
    propose_create_site,
    propose_delete_site,
    propose_report_breakdown,
    propose_retire_machine,
    propose_return_machine,
    propose_terminate_employee,
    propose_update_machine,
    propose_update_machine_inspection_date,
    propose_update_reservation,
    propose_update_service_record,
    propose_update_site,
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

    def test_inspection_type_preview_mentions_auto_next_date(self, user_service_perms, koparka_001):
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
        result = propose_create_service_record(self._params(cost=0.0), user=user_service_perms)
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
        params = UpdateMachineInspectionDateParams(machine_uid="KOP-001", next_inspection_date=past)
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
        result = execute_confirmed_action("create_service_record", params, user=user_service_perms)
        assert "Wpis serwisowy" in result
        assert "KOP-001" in result
        # DB stan się zmienił.
        assert ServiceRecord.objects.filter(machine=koparka_001).count() == 1
        record = ServiceRecord.objects.get(machine=koparka_001)
        assert record.record_type == "naprawa"
        assert record.description == "Wymiana baterii"
        assert float(record.cost.amount) == 308.0

    def test_execute_create_inspection_bumps_machine_date(self, user_service_perms, koparka_001):
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
        assert float(record.cost.amount) == 350.0
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


# =============================================================================
# Faza B — rezerwacje extras (confirm / complete / update / breakdown)
# =============================================================================


@pytest.fixture
def user_all_write_perms(db):
    """User z wszystkimi write permissions — testy ktore krzyzuja apps
    (np. report_breakdown wymaga reservations + service + machines)."""
    user_model = get_user_model()
    u = user_model.objects.create_user(username="all-write-tester", password="x")
    perms = [
        ("reservations", "add_reservation"),
        ("reservations", "change_reservation"),
        ("reservations", "view_reservation"),
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


@pytest.fixture
def reservation_confirmed(db, koparka_001):
    """POTWIERDZONA rezerwacja — baza dla complete_reservation."""
    today = date.today()
    return Reservation.objects.create(
        machine=koparka_001,
        start_date=today,
        end_date=today + timedelta(days=5),
        person="Operator Test",
        status=Reservation.Status.POTWIERDZONA,
    )


@pytest.mark.django_db
class TestProposeConfirmReservation:
    def test_proposes_confirmation_for_pending(self, user_full_perms, reservation_pending):
        params = ConfirmReservationParams(reservation_id=reservation_pending.pk)
        result = propose_confirm_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "confirm_reservation"
        assert "Oczekująca → Potwierdzona" in payload["preview"]

    def test_rejects_non_pending(self, user_full_perms, reservation_confirmed):
        params = ConfirmReservationParams(reservation_id=reservation_confirmed.pk)
        result = propose_confirm_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "tylko OCZEKUJACA" in payload["error"]

    def test_rejects_nonexistent_reservation(self, user_full_perms):
        params = ConfirmReservationParams(reservation_id=99999)
        result = propose_confirm_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert "error" in payload

    def test_rejects_user_without_perm(self, user_view_only, reservation_pending):
        params = ConfirmReservationParams(reservation_id=reservation_pending.pk)
        result = propose_confirm_reservation(params, user=user_view_only)
        payload = json.loads(result)
        assert "error" in payload


@pytest.mark.django_db
class TestProposeCompleteReservation:
    def test_proposes_completion_for_confirmed(self, user_full_perms, reservation_confirmed):
        params = CompleteReservationParams(reservation_id=reservation_confirmed.pk)
        result = propose_complete_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "complete_reservation"
        assert "Potwierdzona → Zakończona" in payload["preview"]

    def test_accepts_actual_return_date(self, user_full_perms, reservation_confirmed):
        actual = date.today().isoformat()
        params = CompleteReservationParams(
            reservation_id=reservation_confirmed.pk, actual_return_date=actual
        )
        result = propose_complete_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert "proposed_action" in payload
        assert actual in payload["preview"]

    def test_rejects_future_actual_return(self, user_full_perms, reservation_confirmed):
        future = (date.today() + timedelta(days=10)).isoformat()
        params = CompleteReservationParams(
            reservation_id=reservation_confirmed.pk, actual_return_date=future
        )
        result = propose_complete_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "przyszłości" in payload["error"]

    def test_rejects_non_confirmed(self, user_full_perms, reservation_pending):
        params = CompleteReservationParams(reservation_id=reservation_pending.pk)
        result = propose_complete_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "tylko POTWIERDZONA" in payload["error"]


@pytest.mark.django_db
class TestProposeUpdateReservation:
    def test_proposes_date_change(self, user_full_perms, reservation_pending):
        new_end = (reservation_pending.end_date + timedelta(days=2)).isoformat()
        params = UpdateReservationParams(reservation_id=reservation_pending.pk, end_date=new_end)
        result = propose_update_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "update_reservation"
        assert new_end in payload["preview"]

    def test_rejects_end_before_start(self, user_full_perms, reservation_pending):
        # end_date < start_date po proponowanej zmianie.
        new_end = (reservation_pending.start_date - timedelta(days=1)).isoformat()
        params = UpdateReservationParams(reservation_id=reservation_pending.pk, end_date=new_end)
        result = propose_update_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "Data końca musi być >= data początku" in payload["error"]

    def test_rejects_when_no_changes(self, user_full_perms, reservation_pending):
        params = UpdateReservationParams(reservation_id=reservation_pending.pk)
        result = propose_update_reservation(params, user=user_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "Brak zmian" in payload["error"]


@pytest.mark.django_db
class TestProposeReportBreakdown:
    def test_proposes_breakdown_for_open_reservation(
        self, user_all_write_perms, reservation_confirmed
    ):
        params = ReportBreakdownParams(
            reservation_id=reservation_confirmed.pk,
            description="Silnik dymi, nagła awaria hydrauliki.",
        )
        result = propose_report_breakdown(params, user=user_all_write_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "report_breakdown"
        assert "Silnik dymi" in payload["preview"]
        assert "W serwisie" in payload["preview"]

    def test_rejects_short_description_at_pydantic_level(self):
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            ReportBreakdownParams(reservation_id=1, description="abc")  # < 5 chars

    def test_rejects_closed_reservation(self, user_all_write_perms, koparka_001):
        from reservations.models import Reservation

        today = date.today()
        closed = Reservation.objects.create(
            machine=koparka_001,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=5),
            person="Test",
            status=Reservation.Status.ZAKONCZONA,
        )
        params = ReportBreakdownParams(reservation_id=closed.pk, description="Cokolwiek opis.")
        result = propose_report_breakdown(params, user=user_all_write_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "zamknięta" in payload["error"]


@pytest.mark.django_db
class TestExecuteReservationExtras:
    """Pełna ścieżka execute dla 4 nowych akcji rezerwacyjnych."""

    def test_execute_confirm_reservation(self, user_full_perms, reservation_pending):
        result = execute_confirmed_action(
            "confirm_reservation",
            {"reservation_id": reservation_pending.pk},
            user=user_full_perms,
        )
        assert "potwierdzona" in result
        reservation_pending.refresh_from_db()
        assert reservation_pending.status == Reservation.Status.POTWIERDZONA

    def test_execute_complete_reservation(self, user_full_perms, reservation_confirmed):
        result = execute_confirmed_action(
            "complete_reservation",
            {"reservation_id": reservation_confirmed.pk, "actual_return_date": None},
            user=user_full_perms,
        )
        assert "zakończona" in result
        reservation_confirmed.refresh_from_db()
        assert reservation_confirmed.status == Reservation.Status.ZAKONCZONA

    def test_execute_update_reservation_changes_person(self, user_full_perms, reservation_pending):
        result = execute_confirmed_action(
            "update_reservation",
            {
                "reservation_id": reservation_pending.pk,
                "person": "Nowa Osoba",
                "start_date": None,
                "end_date": None,
                "notes": None,
            },
            user=user_full_perms,
        )
        assert "zaktualizowana" in result
        reservation_pending.refresh_from_db()
        assert reservation_pending.person == "Nowa Osoba"

    def test_execute_report_breakdown(self, user_all_write_perms, reservation_confirmed):
        result = execute_confirmed_action(
            "report_breakdown",
            {
                "reservation_id": reservation_confirmed.pk,
                "description": "Pompa hydrauliki padła w trakcie pracy.",
            },
            user=user_all_write_perms,
        )
        assert "zgłoszona" in result
        reservation_confirmed.refresh_from_db()
        assert reservation_confirmed.status == Reservation.Status.ZAKONCZONA
        # Maszyna powinna być w serwisie.
        reservation_confirmed.machine.refresh_from_db()
        assert reservation_confirmed.machine.status == Machine.Status.W_SERWISIE
        # ServiceRecord typu naprawa powstał.
        assert ServiceRecord.objects.filter(
            machine=reservation_confirmed.machine,
            record_type=ServiceRecord.RecordType.NAPRAWA,
        ).exists()


# =============================================================================
# Faza C — machine CRUD + state transitions
# =============================================================================


@pytest.fixture
def user_machine_full_perms(db):
    """User z PEŁNYMI uprawnieniami machine (add + change + view)."""
    user_model = get_user_model()
    u = user_model.objects.create_user(username="machine-full-tester", password="x")
    perms = [
        ("machines", "add_machine"),
        ("machines", "change_machine"),
        ("machines", "view_machine"),
    ]
    for app_label, codename in perms:
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        u.user_permissions.add(perm)
    return user_model.objects.get(pk=u.pk)


@pytest.fixture
def koparka_in_service(db):
    """Maszyna ze statusem W serwisie — baza dla close_repair testów."""
    return Machine.objects.create(
        uid="SVC-001",
        name="Maszyna w serwisie",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_SERWISIE,
    )


@pytest.fixture
def koparka_on_site(db):
    """Maszyna ze statusem Na budowie — baza dla return testów."""
    return Machine.objects.create(
        uid="SITE-001",
        name="Maszyna na budowie",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.NA_BUDOWIE,
        location="Budowa testowa",
    )


@pytest.mark.django_db
class TestProposeCreateMachine:
    def test_proposes_new_machine(self, user_machine_full_perms):
        params = CreateMachineParams(
            uid="NEW-100",
            name="Nowa testowa koparka",
            machine_type="koparka",
            model="CAT 320D",
            manufacturer="Caterpillar",
        )
        result = propose_create_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "create_machine"
        assert "NEW-100" in payload["preview"]
        assert "Caterpillar" in payload["preview"]

    def test_rejects_duplicate_uid(self, user_machine_full_perms, koparka_001):
        params = CreateMachineParams(uid="KOP-001", name="Duplikat")
        result = propose_create_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "juz istnieje" in payload["error"]

    def test_rejects_user_without_perm(self, user_view_only):
        params = CreateMachineParams(uid="NEW-200", name="Bez uprawnien")
        result = propose_create_machine(params, user=user_view_only)
        payload = json.loads(result)
        assert "error" in payload


@pytest.mark.django_db
class TestProposeUpdateMachine:
    def test_proposes_name_change(self, user_machine_full_perms, koparka_001):
        params = UpdateMachineParams(machine_uid="KOP-001", name="Nowa nazwa")
        result = propose_update_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "update_machine"
        assert "Nowa nazwa" in payload["preview"]

    def test_rejects_when_no_changes(self, user_machine_full_perms, koparka_001):
        params = UpdateMachineParams(machine_uid="KOP-001")
        result = propose_update_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "Brak zmian" in payload["error"]


@pytest.mark.django_db
class TestProposeReturnMachine:
    def test_proposes_return_from_site(self, user_machine_full_perms, koparka_on_site):
        params = ReturnMachineParams(machine_uid="SITE-001")
        result = propose_return_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "return_machine"
        assert "W magazynie" in payload["preview"]

    def test_rejects_already_in_warehouse(self, user_machine_full_perms, koparka_001):
        # koparka_001 ma status W_MAGAZYNIE z fixture.
        params = ReturnMachineParams(machine_uid="KOP-001")
        result = propose_return_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "juz jest w magazynie" in payload["error"]


@pytest.mark.django_db
class TestProposeCloseRepairMachine:
    def test_proposes_close_for_in_service(self, user_machine_full_perms, koparka_in_service):
        params = CloseRepairMachineParams(machine_uid="SVC-001")
        result = propose_close_repair_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "close_repair_machine"
        assert "W serwisie → W magazynie" in payload["preview"]

    def test_rejects_machine_not_in_service(self, user_machine_full_perms, koparka_001):
        params = CloseRepairMachineParams(machine_uid="KOP-001")
        result = propose_close_repair_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "tylko dla 'W serwisie'" in payload["error"]


@pytest.mark.django_db
class TestProposeRetireMachine:
    def test_proposes_retire_with_reason(self, user_machine_full_perms, koparka_001):
        params = RetireMachineParams(machine_uid="KOP-001", reason="Naprawa za droga")
        result = propose_retire_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "retire_machine"
        assert "Wycofana" in payload["preview"]
        assert "Naprawa za droga" in payload["preview"]

    def test_rejects_already_retired(self, user_machine_full_perms, koparka_001):
        koparka_001.status = Machine.Status.WYCOFANA
        koparka_001.save(update_fields=["status", "updated_at"])
        params = RetireMachineParams(machine_uid="KOP-001")
        result = propose_retire_machine(params, user=user_machine_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "juz wycofana" in payload["error"]


@pytest.mark.django_db
class TestExecuteMachineActions:
    """Pełna ścieżka execute dla 5 nowych akcji maszyn."""

    def test_execute_create_machine(self, user_machine_full_perms):
        result = execute_confirmed_action(
            "create_machine",
            {
                "uid": "EXE-001",
                "name": "Exec test koparka",
                "machine_type": "koparka",
                "model": "Test 1",
                "location": "Magazyn",
                "manufacturer": "TestCo",
                "serial_number": "SN-001",
            },
            user=user_machine_full_perms,
        )
        assert "utworzona" in result
        assert Machine.objects.filter(uid="EXE-001").exists()

    def test_execute_update_machine(self, user_machine_full_perms, koparka_001):
        result = execute_confirmed_action(
            "update_machine",
            {
                "machine_id": koparka_001.pk,
                "machine_uid": koparka_001.uid,
                "name": "Zaktualizowana",
                "location": "Nowy magazyn",
                "notes": None,
                "manufacturer": None,
                "serial_number": None,
            },
            user=user_machine_full_perms,
        )
        assert "zaktualizowana" in result
        koparka_001.refresh_from_db()
        assert koparka_001.name == "Zaktualizowana"
        assert koparka_001.location == "Nowy magazyn"

    def test_execute_return_machine(self, user_machine_full_perms, koparka_on_site):
        result = execute_confirmed_action(
            "return_machine",
            {"machine_id": koparka_on_site.pk, "machine_uid": koparka_on_site.uid},
            user=user_machine_full_perms,
        )
        assert "wróciła do magazynu" in result
        koparka_on_site.refresh_from_db()
        assert koparka_on_site.status == Machine.Status.W_MAGAZYNIE

    def test_execute_close_repair(self, user_machine_full_perms, koparka_in_service):
        result = execute_confirmed_action(
            "close_repair_machine",
            {"machine_id": koparka_in_service.pk, "machine_uid": koparka_in_service.uid},
            user=user_machine_full_perms,
        )
        assert "zakończona" in result
        koparka_in_service.refresh_from_db()
        assert koparka_in_service.status == Machine.Status.W_MAGAZYNIE

    def test_execute_retire(self, user_machine_full_perms, koparka_001):
        result = execute_confirmed_action(
            "retire_machine",
            {
                "machine_id": koparka_001.pk,
                "machine_uid": koparka_001.uid,
                "reason": "Stara",
            },
            user=user_machine_full_perms,
        )
        assert "wycofana" in result
        koparka_001.refresh_from_db()
        assert koparka_001.status == Machine.Status.WYCOFANA
        assert "Stara" in koparka_001.notes


# =============================================================================
# Faza D — construction sites (create / update / delete)
# =============================================================================


@pytest.fixture
def user_site_full_perms(db):
    user_model = get_user_model()
    u = user_model.objects.create_user(username="site-full-tester", password="x")
    for app_label, codename in [
        ("reservations", "add_constructionsite"),
        ("reservations", "change_constructionsite"),
        ("reservations", "delete_constructionsite"),
        ("reservations", "view_constructionsite"),
    ]:
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        u.user_permissions.add(perm)
    return user_model.objects.get(pk=u.pk)


@pytest.mark.django_db
class TestProposeCreateSite:
    def test_proposes_new_site(self, user_site_full_perms):
        params = CreateSiteParams(
            project_number="BUD-2026-099",
            name="Test budowy",
            address="ul. Testowa 1, Warszawa",
            client_name="TestCorp",
        )
        result = propose_create_site(params, user=user_site_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "create_site"
        assert "BUD-2026-099" in payload["preview"]
        assert "TestCorp" in payload["preview"]

    def test_rejects_duplicate_project_number(self, user_site_full_perms, site_bud_007):
        params = CreateSiteParams(
            project_number="BUD-2026-007",
            name="Duplikat",
            address="ul. X 1",
        )
        result = propose_create_site(params, user=user_site_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "juz istnieje" in payload["error"]

    def test_rejects_invalid_project_number_format(self):
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            CreateSiteParams(project_number="WRONG-FORMAT", name="x", address="y")


@pytest.mark.django_db
class TestProposeUpdateSite:
    def test_proposes_name_change(self, user_site_full_perms, site_bud_007):
        params = UpdateSiteParams(project_number="BUD-2026-007", name="Nowa nazwa testowa")
        result = propose_update_site(params, user=user_site_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "update_site"
        assert "Nowa nazwa testowa" in payload["preview"]

    def test_rejects_when_no_changes(self, user_site_full_perms, site_bud_007):
        params = UpdateSiteParams(project_number="BUD-2026-007")
        result = propose_update_site(params, user=user_site_full_perms)
        payload = json.loads(result)
        assert "error" in payload


@pytest.mark.django_db
class TestProposeDeleteSite:
    def test_proposes_delete_for_empty_site(self, user_site_full_perms, site_bud_007):
        params = DeleteSiteParams(project_number="BUD-2026-007")
        result = propose_delete_site(params, user=user_site_full_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "delete_site"
        assert "nieodwracalna" in payload["preview"].lower()

    def test_rejects_site_with_active_reservations(
        self, user_site_full_perms, site_bud_007, reservation_pending
    ):
        # Powiąż reservation z budową, żeby site miał has_active_reservations=True.
        reservation_pending.site = site_bud_007
        reservation_pending.save(update_fields=["site"])
        params = DeleteSiteParams(project_number="BUD-2026-007")
        result = propose_delete_site(params, user=user_site_full_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "aktywnych rezerwacji" in payload["error"]


# =============================================================================
# Faza E — employees (terminate / anonymize — GDPR)
# =============================================================================


@pytest.fixture
def user_account_perms(db):
    user_model = get_user_model()
    u = user_model.objects.create_user(
        username="account-admin", password="x", first_name="Admin", last_name="HR"
    )
    perm = Permission.objects.get(
        content_type__app_label="accounts", codename="change_employeeprofile"
    )
    u.user_permissions.add(perm)
    return user_model.objects.get(pk=u.pk)


@pytest.fixture
def active_employee_profile(db):
    """Aktywny pracownik z EmployeeProfile + user.is_active=True."""
    from accounts.models import EmployeeProfile

    user_model = get_user_model()
    employee_user = user_model.objects.create_user(
        username="jkowalski",
        password="x",
        first_name="Jan",
        last_name="Kowalski",
        email="jan@example.com",
        is_active=True,
    )
    profile, _ = EmployeeProfile.objects.get_or_create(
        user=employee_user,
        defaults={"is_active_employee": True},
    )
    if not profile.is_active_employee:
        profile.is_active_employee = True
        profile.save()
    return profile


@pytest.mark.django_db
class TestProposeTerminateEmployee:
    def test_proposes_termination_with_reason(self, user_account_perms, active_employee_profile):
        params = TerminateEmployeeParams(username="jkowalski", reason="Rezygnacja na własną prośbę")
        result = propose_terminate_employee(params, user=user_account_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "terminate_employee"
        assert "Jan Kowalski" in payload["preview"]
        assert "Rezygnacja" in payload["preview"]

    def test_rejects_nonexistent_username(self, user_account_perms):
        params = TerminateEmployeeParams(username="ghost-user", reason="Test")
        result = propose_terminate_employee(params, user=user_account_perms)
        payload = json.loads(result)
        assert "error" in payload

    def test_rejects_short_reason_at_pydantic_level(self):
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            TerminateEmployeeParams(username="x", reason="ab")  # < 3 chars

    def test_rejects_self_termination(self, user_account_perms):
        from accounts.models import EmployeeProfile

        EmployeeProfile.objects.get_or_create(
            user=user_account_perms, defaults={"is_active_employee": True}
        )
        params = TerminateEmployeeParams(username="account-admin", reason="Self-fire attempt")
        result = propose_terminate_employee(params, user=user_account_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "samego siebie" in payload["error"]


@pytest.mark.django_db
class TestProposeAnonymizeEmployee:
    def test_proposes_anonymization_with_warning(self, user_account_perms, active_employee_profile):
        params = AnonymizeEmployeeParams(username="jkowalski")
        result = propose_anonymize_employee(params, user=user_account_perms)
        payload = json.loads(result)
        assert payload["proposed_action"] == "anonymize_employee"
        assert "NIEODWRACALNA" in payload["preview"]
        assert "GDPR Art.17" in payload["preview"]

    def test_rejects_already_anonymized(self, user_account_perms, active_employee_profile):
        from django.utils import timezone

        active_employee_profile.is_anonymized = True
        active_employee_profile.anonymized_at = timezone.now()
        active_employee_profile.save()
        params = AnonymizeEmployeeParams(username="jkowalski")
        result = propose_anonymize_employee(params, user=user_account_perms)
        payload = json.loads(result)
        assert "error" in payload
        assert "już zanonimizowany" in payload["error"]


@pytest.mark.django_db
class TestExecuteSiteAndEmployeeActions:
    def test_execute_create_site(self, user_site_full_perms):
        result = execute_confirmed_action(
            "create_site",
            {
                "project_number": "BUD-2026-200",
                "name": "Exec test budowy",
                "address": "ul. Exec 1",
                "client_name": "ExecCorp",
                "city": "Lublin",
            },
            user=user_site_full_perms,
        )
        assert "BUD-2026-200" in result
        from reservations.models import ConstructionSite

        assert ConstructionSite.objects.filter(project_number="BUD-2026-200").exists()

    def test_execute_terminate_employee(self, user_account_perms, active_employee_profile):
        result = execute_confirmed_action(
            "terminate_employee",
            {
                "user_id": active_employee_profile.user.pk,
                "username": "jkowalski",
                "reason": "Test termination",
            },
            user=user_account_perms,
        )
        assert "zakończone" in result
        active_employee_profile.refresh_from_db()
        assert not active_employee_profile.is_active_employee
        active_employee_profile.user.refresh_from_db()
        assert not active_employee_profile.user.is_active

    def test_execute_anonymize_employee(self, user_account_perms, active_employee_profile):
        result = execute_confirmed_action(
            "anonymize_employee",
            {
                "user_id": active_employee_profile.user.pk,
                "username": "jkowalski",
            },
            user=user_account_perms,
        )
        assert "zanonimizowany" in result
        active_employee_profile.refresh_from_db()
        assert active_employee_profile.is_anonymized
        active_employee_profile.user.refresh_from_db()
        # PII powinno być zastąpione hashem anon-XXXX.
        assert active_employee_profile.user.username.startswith("anon-")
        assert active_employee_profile.user.first_name == "Anonimowy"
