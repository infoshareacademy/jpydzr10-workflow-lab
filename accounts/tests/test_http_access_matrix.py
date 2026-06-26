"""Macierz dostępu na poziomie HTTP — bramki RBAC per rola dla akcji rezerwacji.

Uzupełnia ``test_rbac_matrix`` (poziom ``has_perm``) o realny przebieg żądania
przez widok: czy bramka ``permission_required`` faktycznie zwraca 403 dla roli,
która nie powinna móc wykonać akcji. Pełna macierz HTTP została zweryfikowana
probe'em w FAZIE B (2026-06-26); tu utrwalamy najważniejszą regresję — kierownik
SKŁADA wnioski, ale NIE zatwierdza (potwierdza magazynier/admin).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts.models import EmployeeProfile
from machines.models import Machine
from reservations.models import ConstructionSite, Reservation

User = get_user_model()
pytestmark = pytest.mark.django_db

_SEQ = [0]


def _role_user(function, *, superuser=False):
    _SEQ[0] += 1
    n = _SEQ[0]
    user = User.objects.create_user(
        f"role{n}",
        password="x",
        email=f"role{n}@t.test",
        is_staff=superuser,
        is_superuser=superuser,
    )
    user.profile.function = function
    user.profile.save()
    return User.objects.get(pk=user.pk)


@pytest.fixture
def roles():
    return {
        "admin": _role_user(EmployeeProfile.Function.ADMIN, superuser=True),
        "magazynier": _role_user(EmployeeProfile.Function.MAGAZYNIER),
        "kierownik": _role_user(EmployeeProfile.Function.KIEROWNIK),
        "montazysta": _role_user(EmployeeProfile.Function.MONTAZYSTA),
    }


def _machine():
    _SEQ[0] += 1
    return Machine.objects.create(
        uid=f"AM-{_SEQ[0]:05d}",
        name="K",
        machine_type=Machine.Type.KOPARKA,
        status=Machine.Status.W_MAGAZYNIE,
    )


def _site():
    _SEQ[0] += 1
    return ConstructionSite.objects.create(
        project_number=f"BUD-2026-{_SEQ[0] % 1000:03d}",
        name="S",
        status=ConstructionSite.Status.AKTYWNA,
    )


def _reservation(creator, status=Reservation.Status.OCZEKUJACA):
    return Reservation.objects.create(
        machine=_machine(),
        site=_site(),
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
        person="X",
        status=status,
        created_by=creator,
    )


# Akcje zatwierdzające rezerwację: dozwolone dla admin+magazynier, 403 dla
# kierownik+montażysta. Każda używa permission ``reservations.change_reservation``.
_APPROVAL_ACTIONS = [
    "confirm",
    "cancel",
    "complete",
    "change_operator",
    "swap_machine",
    "report_breakdown",
]


@pytest.mark.parametrize("action", _APPROVAL_ACTIONS)
@pytest.mark.parametrize("role", ["admin", "magazynier", "kierownik", "montazysta"])
def test_reservation_approval_gate_by_role(roles, role, action):
    user = roles[role]
    status = (
        Reservation.Status.POTWIERDZONA
        if action in ("complete", "report_breakdown")
        else Reservation.Status.OCZEKUJACA
    )
    res = _reservation(roles["admin"], status=status)
    client = Client()
    client.force_login(user)
    resp = client.post(reverse(f"reservations:{action}", args=[res.pk]))

    if role in ("admin", "magazynier"):
        assert resp.status_code != 403, f"{role} powinien móc {action}"
    else:
        assert resp.status_code == 403, (
            f"{role} NIE powinien móc {action} (kier=składa, monter=read-only)"
        )


@pytest.mark.parametrize(
    ("role", "expected_denied"),
    [("admin", False), ("magazynier", True), ("kierownik", False), ("montazysta", True)],
)
def test_site_delete_gate_by_role(roles, role, expected_denied):
    """Usuwanie budowy: admin + kierownik tak; magazynier + montażysta 403."""
    site = _site()
    client = Client()
    client.force_login(roles[role])
    resp = client.post(reverse("reservations:site_delete", args=[site.pk]))
    if expected_denied:
        assert resp.status_code == 403
    else:
        assert resp.status_code != 403


@pytest.mark.parametrize("role", ["magazynier", "kierownik", "montazysta"])
def test_reservation_edit_is_admin_only(roles, role):
    """Edycja formularza rezerwacji = wyłącznie admin (pozostali 403)."""
    res = _reservation(roles["admin"])
    client = Client()
    client.force_login(roles[role])
    resp = client.get(reverse("reservations:update", args=[res.pk]))
    assert resp.status_code == 403
