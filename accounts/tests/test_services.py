"""Testy serwisów warstwy biznesowej aplikacji accounts.

``register_employee`` zwraca utworzony :class:`EmployeeProfile`, sam
``User`` jest dostępny przez ``profile.user``. ``terminate_employee``
przyjmuje profil i ustawia ``is_active_employee=False`` oraz
``user.is_active=False`` w jednej transakcji.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import EmployeeProfile
from accounts.services import (
    anonymize_employee,
    register_employee,
    terminate_employee,
    update_profile,
)

User = get_user_model()


@pytest.mark.django_db
def test_register_employee_creates_user_and_profile():
    """Happy path — User + EmployeeProfile powstaje, hasło hashowane."""
    profile = register_employee(
        username="test123",
        email="test@example.com",
        password="ComplexPass!2026",
    )
    assert isinstance(profile, EmployeeProfile)
    assert profile.user.username == "test123"
    assert profile.user.email == "test@example.com"
    assert profile.user.is_active is True
    # check_password używa zahashowanego stringa, nie plaintext
    assert profile.user.check_password("ComplexPass!2026")


@pytest.mark.django_db
def test_register_employee_default_function():
    """Brak ``function`` w wywołaniu → domyślnie MONTAZYSTA (signal default)."""
    profile = register_employee(
        username="u1",
        email="u1@example.com",
        password="StrongP@ss!1",
    )
    assert profile.function == EmployeeProfile.Function.MONTAZYSTA


@pytest.mark.django_db
def test_register_employee_custom_function_persisted():
    """Przekazana ``function`` nadpisuje default z signalu."""
    profile = register_employee(
        username="u2",
        email="u2@example.com",
        password="StrongP@ss!2",
        function=EmployeeProfile.Function.KIEROWNIK,
    )
    assert profile.function == EmployeeProfile.Function.KIEROWNIK


@pytest.mark.django_db
def test_terminate_deactivates_user_and_profile():
    """``terminate_employee`` flipuje obie flagi: profil + Django User.is_active."""
    profile = register_employee(
        username="u3",
        email="u3@example.com",
        password="StrongP@ss!3",
    )
    terminate_employee(profile=profile)
    profile.refresh_from_db()
    profile.user.refresh_from_db()
    assert profile.is_active_employee is False
    assert profile.user.is_active is False


@pytest.mark.django_db
def test_register_employee_accepts_valid_phone():
    """Poprawny numer E.164 jest zapisany w profilu nowego pracownika."""
    profile = register_employee(
        username="phoneok",
        email="phoneok@example.com",
        password="StrongP@ss!PH1",
        phone="+48 600 700 800",
    )
    assert profile.phone == "+48600700800"


@pytest.mark.django_db
def test_register_employee_rejects_invalid_phone_and_creates_no_user():
    """Niepoprawny numer → ValidationError; transakcja cofa też utworzenie User.

    register_employee zapisuje przez ``save(update_fields=...)`` bez full_clean,
    więc wymuszenie E.164 spoczywa na ``EmployeeProfile.save``. Dzięki
    ``@transaction.atomic`` raise rollbackuje również ``User.objects.create_user``
    — nie zostaje osierocone konto.
    """
    with pytest.raises(ValidationError):
        register_employee(
            username="phonebad",
            email="phonebad@example.com",
            password="StrongP@ss!PH2",
            phone="+0123",  # niepoprawny E.164
        )
    assert not User.objects.filter(username="phonebad").exists()


@pytest.mark.django_db
def test_register_employee_validates_weak_password():
    """Walidacja hasła (min. długość / common / HIBP) — too short fails fast."""
    with pytest.raises(ValidationError):
        register_employee(
            username="u4",
            email="u4@example.com",
            password="123",
        )


@pytest.mark.django_db
def test_terminate_employee_sets_inactive():
    """Terminacja ustawia ``user.is_active=False`` i datę zakończenia na dzisiaj."""
    from django.utils import timezone

    profile = register_employee(
        username="term1",
        email="term1@example.com",
        password="StrongP@ss!4",
    )
    terminate_employee(profile, reason="koniec kontraktu")
    profile.refresh_from_db()
    profile.user.refresh_from_db()
    assert profile.is_active_employee is False
    assert profile.user.is_active is False
    assert profile.termination_date == timezone.localdate()
    assert profile.termination_reason == "koniec kontraktu"


@pytest.mark.django_db
def test_terminate_employee_clears_groups():
    """Terminacja czyści wszystkie grupy użytkownika (revoke RBAC)."""
    from django.contrib.auth.models import Group

    profile = register_employee(
        username="term2",
        email="term2@example.com",
        password="StrongP@ss!5",
    )
    # Dodajemy do grupy ręcznie (function=MONTAZYSTA nie mapuje się na żadną).
    # Grupa istnieje już po migracji RBAC, więc get_or_create zamiast create.
    grp, _ = Group.objects.get_or_create(name="Magazynierzy")
    profile.user.groups.add(grp)
    assert profile.user.groups.count() == 1

    terminate_employee(profile)
    profile.user.refresh_from_db()
    assert profile.user.groups.count() == 0


@pytest.mark.django_db
def test_terminate_employee_clears_admin_group():
    """Pełen cykl ADMIN: sygnał nadaje Administratorzy, terminacja je czyści.

    Inaczej niż ``test_terminate_employee_clears_groups`` (ręczne dodanie do
    grupy), tu grupa pochodzi z sygnału RBAC dla funkcji ADMIN — sprawdzamy, że
    offboarding rzeczywiście odbiera uprawnienia nadane automatycznie.
    """
    profile = register_employee(
        username="adminterm",
        email="adminterm@example.com",
        password="StrongP@ss!ADM",
        function=EmployeeProfile.Function.ADMIN,
    )
    assert profile.user.groups.filter(name="Administratorzy").exists()

    terminate_employee(profile)
    profile.user.refresh_from_db()
    assert profile.user.groups.count() == 0


@pytest.mark.django_db
def test_terminate_employee_kills_sessions():
    """Terminacja kasuje aktywne sesje użytkownika z bazy sessions."""
    from importlib import import_module

    from django.conf import settings
    from django.contrib.sessions.models import Session

    profile = register_employee(
        username="term3",
        email="term3@example.com",
        password="StrongP@ss!6",
    )
    # Tworzymy realną sesję dla usera (jak po loginie).
    engine = import_module(settings.SESSION_ENGINE)
    session = engine.SessionStore()
    session["_auth_user_id"] = str(profile.user.pk)
    session.save()
    assert Session.objects.count() == 1

    terminate_employee(profile)
    assert Session.objects.count() == 0


@pytest.mark.django_db
def test_terminate_employee_rejects_anonymized():
    """Próba terminacji już zanonimizowanego profilu rzuca ValidationError."""
    profile = register_employee(
        username="term4",
        email="term4@example.com",
        password="StrongP@ss!7",
    )
    anonymize_employee(profile)
    with pytest.raises(ValidationError):
        terminate_employee(profile)


@pytest.mark.django_db
def test_anonymize_employee_scrambles_pii():
    """Anonimizacja zastępuje first_name/last_name/email/username hashem."""
    profile = register_employee(
        username="orig1",
        email="orig1@example.com",
        password="StrongP@ss!8",
    )
    profile.user.first_name = "Jan"
    profile.user.last_name = "Kowalski"
    profile.user.save()

    anonymize_employee(profile)
    profile.refresh_from_db()
    profile.user.refresh_from_db()

    assert profile.is_anonymized is True
    assert profile.anonymized_at is not None
    assert profile.user.first_name == "Anonimowy"
    assert profile.user.last_name.startswith("Pracownik-")
    assert profile.user.email.startswith("anon-")
    assert profile.user.email.endswith("@deleted.local")
    assert profile.user.username.startswith("anon-")
    assert "orig1" not in profile.user.username


@pytest.mark.django_db
def test_update_profile_silently_ignores_unknown_fields():
    """Wave 4 E2 P1 #12: update_profile() whitelist'uje pola, ignoruje resztę.

    Próba ustawienia ``is_anonymized=True`` przez update_profile (np. malicious
    POST z pola hidden) musi być cicho zignorowana — to chroni przed
    nieautoryzowanym ustawieniem GDPR flag przez user-a.
    """
    profile = register_employee(
        username="upd1",
        email="upd1@example.com",
        password="StrongP@ss!UP1",
    )
    update_profile(
        profile,
        phone="+48123456789",
        is_anonymized=True,  # NIE w whitelist
        unknown_field="x",  # NIE w whitelist
    )
    profile.refresh_from_db()
    assert profile.phone == "+48123456789"
    # is_anonymized i unknown_field cicho zignorowane
    assert profile.is_anonymized is False
    assert not hasattr(profile, "unknown_field") or getattr(profile, "unknown_field", None) != "x"


@pytest.mark.django_db
def test_anonymize_employee_scrubs_phone_from_history_as_null():
    """Anonimizacja zeruje telefon w historii spójnie z bieżącym profilem (NULL).

    Bieżący profil po ``save()`` ma ``phone=None``; wszystkie wpisy historyczne
    muszą mieć tę samą reprezentację braku numeru (``None``, NIE ``""``), inaczej
    audyt RODO widzi rozjazd ''/NULL między rekordem a historią.
    """
    profile = register_employee(
        username="anonphone",
        email="anonphone@example.com",
        password="StrongP@ss!APH",
        phone="+48600111222",
    )
    assert profile.phone == "+48600111222"
    # Pewność, że historia w ogóle zawiera numer przed anonimizacją.
    assert profile.history.filter(phone="+48600111222").exists()

    anonymize_employee(profile)
    profile.refresh_from_db()

    assert profile.phone is None
    history_phones = set(profile.history.values_list("phone", flat=True))
    assert history_phones == {None}, f"historia trzyma niespójne wartości: {history_phones}"


@pytest.mark.django_db
def test_anonymize_employee_idempotent():
    """Drugie wywołanie ``anonymize_employee`` na zanonimizowanym profilu — no-op."""
    profile = register_employee(
        username="orig2",
        email="orig2@example.com",
        password="StrongP@ss!9",
    )
    anonymize_employee(profile)
    profile.refresh_from_db()
    first_username = profile.user.username
    first_anon_at = profile.anonymized_at

    anonymize_employee(profile)
    profile.refresh_from_db()
    profile.user.refresh_from_db()
    assert profile.user.username == first_username
    assert profile.anonymized_at == first_anon_at
