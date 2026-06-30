"""Testy modeli i sygnałów aplikacji accounts."""

import pytest
from django.core.exceptions import ValidationError

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


# -----------------------------------------------------------------------------
# EmployeeProfile.save — normalizacja i wymuszenie E.164 na telefonie
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_normalizes_phone_separators():
    """save() oczyszcza separatory wpisanego numeru do ścisłego E.164."""
    user = UserFactory(username="phone-norm")
    profile = user.profile
    profile.phone = "+48 600 100 200"
    profile.save(update_fields=["phone", "updated_at"])
    profile.refresh_from_db()
    assert profile.phone == "+48600100200"


@pytest.mark.django_db
def test_save_stores_empty_phone_as_null():
    """Pusty numer ("" / None) jest zapisywany jako NULL (sentinel braku numeru)."""
    user = UserFactory(username="phone-empty")
    profile = user.profile
    profile.phone = ""
    profile.save(update_fields=["phone", "updated_at"])
    profile.refresh_from_db()
    assert profile.phone is None


@pytest.mark.django_db
def test_save_rejects_invalid_phone_even_without_full_clean():
    """Niepoprawny niepusty numer rzuca ValidationError już w save().

    Krytyczne: ścieżki omijające full_clean (serwis register_employee z
    update_fields, sygnały) nie mogą wpuścić śmieci do bazy. Po raise rekord
    NIE jest utworzony/zmieniony.
    """
    user = UserFactory(username="phone-bad")
    profile = user.profile
    profile.phone = "+0123456789"  # wiodące 0 po "+" → niepoprawny E.164
    with pytest.raises(ValidationError) as exc:
        profile.save(update_fields=["phone", "updated_at"])
    assert "phone" in exc.value.message_dict
    # Numer nie został zapisany.
    profile.refresh_from_db()
    assert profile.phone is None


@pytest.mark.django_db
def test_save_rejects_non_numeric_phone():
    """Wartość nie-numeryczna ("abc") również jest odrzucana w save()."""
    user = UserFactory(username="phone-abc")
    profile = user.profile
    profile.phone = "abc"
    with pytest.raises(ValidationError):
        profile.save(update_fields=["phone", "updated_at"])
