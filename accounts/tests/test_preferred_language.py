"""Testy preferowanego języka UI (EmployeeProfile.preferred_language).

Pole utrwala domyślny język interfejsu per użytkownik (cross-device). Maile są
zawsze dwujęzyczne PL+EN, więc preferred_language dotyczy WYŁĄCZNIE UI. Wybór
jest aplikowany jako ciasteczko języka (mechanizm Django LocaleMiddleware) przy
logowaniu i przy zmianie w profilu.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.forms import ProfileForm
from accounts.services import update_profile

User = get_user_model()
pytestmark = pytest.mark.django_db

COOKIE = settings.LANGUAGE_COOKIE_NAME


def _user(username="lang", password="Planer2026!"):
    return User.objects.create_user(username, password=password, email=f"{username}@demo.test")


def test_default_language_is_pl():
    user = _user()
    assert user.profile.preferred_language == "pl"


def test_profile_form_exposes_language_and_updates():
    user = _user()
    update_profile(user.profile, preferred_language="en")
    user.profile.refresh_from_db()
    assert user.profile.preferred_language == "en"
    assert "preferred_language" in ProfileForm().fields


def test_invalid_language_rejected():
    from django.core.exceptions import ValidationError

    user = _user()
    with pytest.raises(ValidationError):
        update_profile(user.profile, preferred_language="de")  # nie ma w LANGUAGES


def test_login_sets_language_cookie_to_preference(client):
    user = _user("enlogin")
    user.profile.preferred_language = "en"
    user.profile.save()

    resp = client.post(
        reverse("accounts:login"),
        {"username": "enlogin", "password": "Planer2026!"},
    )
    # Zalogowanie kończy się redirectem; ciasteczko języka = preferencja profilu.
    assert resp.status_code == 302
    assert resp.cookies[COOKIE].value == "en"


def test_profile_change_updates_language_cookie(client):
    user = _user("switch")
    client.force_login(user)

    resp = client.post(
        reverse("accounts:profile"),
        {"phone": "", "employee_id": "", "theme_preference": "auto", "preferred_language": "en"},
    )
    assert resp.status_code == 302
    assert resp.cookies[COOKIE].value == "en"
    user.profile.refresh_from_db()
    assert user.profile.preferred_language == "en"
