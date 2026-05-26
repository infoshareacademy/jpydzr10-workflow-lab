"""Testy modeli i sygnałów aplikacji accounts."""

import pytest

from accounts.factories import UserFactory
from accounts.models import EmployeeProfile


@pytest.mark.django_db
def test_user_creation_auto_creates_profile():
    """Sygnał post_save powinien automatycznie utworzyć EmployeeProfile."""
    user = UserFactory(username="anna", email="anna@firma.pl")
    assert hasattr(user, "profile")
    assert isinstance(user.profile, EmployeeProfile)
    assert user.profile.function == EmployeeProfile.Function.MONTAZYSTA


@pytest.mark.django_db
def test_employee_profile_str_uses_full_name():
    """__str__ powinien preferować pełne imię i nazwisko jeśli ustawione."""
    user = UserFactory(
        username="jkowalski",
        email="j@firma.pl",
        first_name="Jan",
        last_name="Kowalski",
    )
    assert str(user.profile) == "Jan Kowalski (Montażysta)"


@pytest.mark.django_db
def test_employee_profile_str_falls_back_to_username():
    """Gdy brak imienia/nazwiska __str__ używa username."""
    user = UserFactory(username="admin1", email="a@firma.pl", first_name="", last_name="")
    assert str(user.profile) == "admin1 (Montażysta)"


@pytest.mark.django_db
def test_employee_profile_default_theme_is_auto():
    """Domyślnie motyw to AUTO (system rozpoznaje preferencje przeglądarki)."""
    user = UserFactory(username="u1")
    assert user.profile.theme_preference == EmployeeProfile.Theme.AUTO


@pytest.mark.django_db
def test_employee_profile_is_active_by_default():
    """Nowo utworzony profil jest aktywny."""
    user = UserFactory(username="u2")
    assert user.profile.is_active_employee is True


@pytest.mark.django_db
def test_employee_profile_gdpr_fields_defaults():
    """Pola GDPR/offboardingu mają sensowne wartości domyślne dla świeżego profilu."""
    user = UserFactory(username="u3")
    profile = user.profile
    assert profile.is_anonymized is False
    assert profile.anonymized_at is None
    assert profile.termination_date is None
    assert profile.termination_reason == ""
