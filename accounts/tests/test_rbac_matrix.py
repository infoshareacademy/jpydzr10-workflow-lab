"""Macierz uprawnień RBAC dla kont demo + identyfikacja po numerze telefonu.

Sprawdza, że role (kierownik / magazynier / montażysta) dostają DOKŁADNIE te
uprawnienia, które przewiduje migracja ``accounts.0003_create_rbac_groups`` —
i że żadne z kont ról nie jest superuserem (superuser maskowałby zepsute RBAC).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from accounts.models import EmployeeProfile
from accounts.services import FUNCTION_GROUP_MAP, user_for_phone

User = get_user_model()


def _make_role_user(username, function, phone, email):
    """Tworzy użytkownika nie-superusera z profilem o danej funkcji + telefonie.

    Zwraca świeżo pobrany obiekt usera, aby cache uprawnień nie zawierał
    nieaktualnych danych po zmianie grup przez sygnał.
    """
    user = User.objects.create_user(username=username, password="x", email=email)
    profile = user.profile
    profile.function = function
    profile.phone = phone
    profile.save(update_fields=["function", "phone", "updated_at"])
    return User.objects.get(pk=user.pk)


@pytest.fixture
def role_users(db):
    return {
        "admin": _make_role_user(
            "admin_demo", EmployeeProfile.Function.ADMIN, "+48600000001", "admin@demo.test"
        ),
        "kierownik": _make_role_user(
            "seba1", EmployeeProfile.Function.KIEROWNIK, "+48600000011", "seba1@demo.test"
        ),
        "magazynier": _make_role_user(
            "seba2", EmployeeProfile.Function.MAGAZYNIER, "+48600000012", "seba2@demo.test"
        ),
        "montazysta": _make_role_user(
            "seba3", EmployeeProfile.Function.MONTAZYSTA, "+48600000013", "seba3@demo.test"
        ),
    }


@pytest.mark.django_db
class TestRoleMatrix:
    def test_none_of_the_role_accounts_is_superuser(self, role_users):
        # Wszystkie konta ról (w tym ADMIN) dostają uprawnienia wyłącznie przez
        # członkostwo w grupie RBAC — NIGDY przez flagę is_superuser, która
        # zamaskowałaby zepsute RBAC (superuser ma has_perm()==True na wszystko).
        for name in ("admin", "kierownik", "magazynier", "montazysta"):
            assert not role_users[name].is_superuser, f"{name} nie może być superuserem"

    def test_role_accounts_have_email(self, role_users):
        for user in role_users.values():
            assert user.email

    def test_magazynier_permissions(self, role_users):
        mag = role_users["magazynier"]
        assert mag.has_perm("reservations.add_reservation")
        assert mag.has_perm("reservations.change_reservation")
        assert mag.has_perm("reservations.delete_reservation")
        assert mag.has_perm("machines.change_machine")
        # Magazynier NIE może usuwać budów (to uprawnienie Kierowników).
        assert not mag.has_perm("reservations.delete_constructionsite")

    def test_kierownik_permissions(self, role_users):
        kier = role_users["kierownik"]
        assert kier.has_perm("reservations.add_reservation")
        assert kier.has_perm("reservations.delete_constructionsite")
        # Kierownik NIE może usuwać rezerwacji (tylko Magazynierzy).
        assert not kier.has_perm("reservations.delete_reservation")
        # ani zmieniać maszyn (np. zwrot/serwis robi magazynier).
        assert not kier.has_perm("machines.change_machine")

    def test_montazysta_is_read_only(self, role_users):
        mont = role_users["montazysta"]
        assert mont.groups.count() == 0
        assert not mont.has_perm("reservations.add_reservation")
        assert not mont.has_perm("reservations.change_reservation")
        assert not mont.has_perm("service.add_servicerecord")

    def test_admin_has_domain_permissions(self, role_users):
        admin = role_users["admin"]
        assert admin.has_perm("reservations.add_reservation")
        assert admin.has_perm("reservations.delete_reservation")
        assert admin.has_perm("machines.change_machine")
        assert admin.has_perm("service.add_servicerecord")

    def test_admin_has_every_domain_app_permission(self, role_users):
        """Administratorzy mają KOMPLET uprawnień z 4 aplikacji domenowych.

        Spot-check 4 uprawnień (powyżej) przeszedłby też, gdyby migracja
        przypadkiem odebrała grupie część permissions. Tu porównujemy pełen
        zbiór uprawnień usera z całością uprawnień aplikacji domenowych —
        ubytek dowolnego permission w grupie Administratorzy zostanie wykryty.
        """
        from django.contrib.auth.models import Permission

        admin = role_users["admin"]
        domain_apps = ("machines", "reservations", "service", "accounts")
        expected = {
            f"{perm.content_type.app_label}.{perm.codename}"
            for perm in Permission.objects.filter(
                content_type__app_label__in=domain_apps
            ).select_related("content_type")
        }
        assert expected, "fixture migracji nie utworzyła żadnych uprawnień domenowych"
        missing = {perm for perm in expected if not admin.has_perm(perm)}
        assert not missing, f"Administratorzy nie mają uprawnień: {sorted(missing)}"


@pytest.mark.django_db
class TestFunctionGroupMapIntegrity:
    def test_every_mapped_group_exists(self):
        """Każda grupa z FUNCTION_GROUP_MAP istnieje (tworzona przez migrację)."""
        from django.contrib.auth.models import Group

        existing = set(Group.objects.values_list("name", flat=True))
        for groups in FUNCTION_GROUP_MAP.values():
            for group_name in groups:
                assert group_name in existing, f"Brak grupy '{group_name}' z migracji RBAC"

    def test_montazysta_accented_value_round_trips_to_db(self):
        """Akcentowana wartość ``montażysta`` przechodzi zapis→odczyt z DB.

        Wartość jest load-bearing: seed/fixtures i klucze ``FUNCTION_GROUP_MAP``
        zakładają dokładnie ``"montażysta"``. Zmiana na ``"montazysta"`` rozjeżdża
        istniejące rekordy i mapowanie grup. Zamiast porównywać literał stałej
        (tautologia), zapisujemy profil i czytamy go z bazy, by potwierdzić, że
        akcentowana wartość faktycznie się utrwala i nie ma 2FA (read-only rola).
        """
        user = User.objects.create_user(username="mont-roundtrip", password="x")
        profile = user.profile
        profile.function = EmployeeProfile.Function.MONTAZYSTA
        profile.save(update_fields=["function", "updated_at"])

        reloaded = EmployeeProfile.objects.get(pk=profile.pk)
        assert reloaded.function == "montażysta"
        # Montażysta jest rolą read-only — nie dostaje żadnej grupy RBAC.
        assert reloaded.user.groups.count() == 0


@pytest.mark.django_db
class TestPhoneUnique:
    def test_duplicate_phone_raises(self):
        """Ograniczenie UNIQUE z migracji blokuje dwa profile z tym samym numerem."""
        from django.db import IntegrityError, transaction

        _make_role_user("p1", EmployeeProfile.Function.MAGAZYNIER, "+48700000001", "p1@t.test")
        with pytest.raises(IntegrityError), transaction.atomic():
            _make_role_user("p2", EmployeeProfile.Function.MAGAZYNIER, "+48700000001", "p2@t.test")

    def test_multiple_null_phones_allowed(self):
        """Wiele profili bez numeru (NULL) współistnieje — NULL nie łamie UNIQUE."""
        u1 = _make_role_user("n1", EmployeeProfile.Function.MONTAZYSTA, None, "n1@t.test")
        u2 = _make_role_user("n2", EmployeeProfile.Function.MONTAZYSTA, "", "n2@t.test")
        assert u1.profile.phone is None
        assert u2.profile.phone is None


@pytest.mark.django_db
class TestUserForPhone:
    def test_resolves_each_role_phone(self, role_users):
        assert user_for_phone("+48600000011") == role_users["kierownik"]
        assert user_for_phone("+48600000012") == role_users["magazynier"]
        assert user_for_phone("+48600000013") == role_users["montazysta"]

    def test_unknown_phone_returns_none(self, role_users):
        assert user_for_phone("+48999999999") is None

    def test_empty_phone_returns_none(self):
        assert user_for_phone("") is None
        assert user_for_phone(None) is None

    def test_inactive_employee_not_resolved(self, role_users):
        profile = role_users["magazynier"].profile
        profile.is_active_employee = False
        profile.save(update_fields=["is_active_employee", "updated_at"])
        assert user_for_phone("+48600000012") is None

    def test_inactive_user_not_resolved(self, role_users):
        user = role_users["kierownik"]
        user.is_active = False
        user.save(update_fields=["is_active"])
        assert user_for_phone("+48600000011") is None
