"""Testy widoków aplikacji accounts (login, logout, profile).

Pokrywają w szczególności:

* widok ``profile`` po refaktorze na service-layer (``update_profile``) —
  happy path (valid POST → redirect + profil zaktualizowany) oraz walidację
  (invalid POST → form errors, 200, profil bez zmian);
* ochronę przed brute-force loginu — rate-limit po IP (django-ratelimit,
  20/h) i lockout page (django-axes ``AXES_LOCKOUT_URL``).
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse

from accounts.factories import UserFactory


@pytest.mark.django_db
def test_profile_get_requires_login(client):
    """GET /profile/ bez logowania → redirect (302) do login."""
    resp = client.get(reverse("accounts:profile"))
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


@pytest.mark.django_db
def test_profile_get_renders_for_logged_user(client):
    """GET /profile/ jako zalogowany user → 200 + ProfileForm w kontekście."""
    user = UserFactory(username="logged-in-user")
    client.force_login(user)
    resp = client.get(reverse("accounts:profile"))
    assert resp.status_code == 200
    assert "form" in resp.context
    assert resp.context["profile"] == user.profile


@pytest.mark.django_db
def test_profile_post_valid_updates_via_service(client):
    """POST z poprawnymi danymi aktualizuje profil i redirectuje na sam siebie."""
    user = UserFactory(username="jan")
    client.force_login(user)
    resp = client.post(
        reverse("accounts:profile"),
        data={
            "phone": "+48 600 100 200",
            "employee_id": "EMP-007",
            "theme_preference": "dark",
        },
    )
    assert resp.status_code == 302
    assert resp["Location"] == reverse("accounts:profile")

    user.profile.refresh_from_db()
    # Wpis z separatorami jest normalizowany do ścisłego E.164.
    assert user.profile.phone == "+48600100200"
    assert user.profile.employee_id == "EMP-007"
    assert user.profile.theme_preference == "dark"


@pytest.mark.django_db
def test_profile_post_invalid_returns_form_errors(client):
    """POST z nieprawidłowymi danymi (zbyt długi phone) zwraca 200 + errors."""
    user = UserFactory(username="ola")
    client.force_login(user)
    original_phone = user.profile.phone
    resp = client.post(
        reverse("accounts:profile"),
        data={
            "phone": "+" * 50,  # > 20 znaków, narusza max_length CharField(20)
            "employee_id": "EMP-008",
            "theme_preference": "auto",
        },
    )
    # Bez redirect — form invalid, render z błędami.
    assert resp.status_code == 200
    assert resp.context["form"].errors
    user.profile.refresh_from_db()
    assert user.profile.phone == original_phone


@pytest.mark.django_db
def test_profile_post_ignores_unwhitelisted_fields(client):
    """update_profile filtruje pola spoza whitelisty — is_anonymized nie da się ustawić."""
    user = UserFactory(username="hak")
    client.force_login(user)
    client.post(
        reverse("accounts:profile"),
        data={
            "phone": "111",
            "employee_id": "X",
            "theme_preference": "auto",
            "is_anonymized": "on",  # próba bypassa
            "is_active_employee": "off",
        },
    )
    user.profile.refresh_from_db()
    assert user.profile.is_anonymized is False
    assert user.profile.is_active_employee is True


@pytest.mark.django_db
def test_profile_post_invalid_theme_choice_returns_errors(client):
    """POST z nieistniejącym ``theme_preference`` zwraca form.errors (choices validate)."""
    user = UserFactory(username="theme-test")
    client.force_login(user)
    resp = client.post(
        reverse("accounts:profile"),
        data={
            "phone": "+48 600 100 200",
            "employee_id": "EMP-009",
            "theme_preference": "nieistniejacy_motyw",  # nie ma w Theme.choices
        },
    )
    assert resp.status_code == 200
    assert resp.context["form"].errors


# =============================================================================
# Brute-force protection: IP rate-limit + lockout page
# =============================================================================
# ``PlanerLoginView`` ma ``@ratelimit(key="ip", rate="20/h", method="POST")``,
# który po 20 POST z tego samego IP rzuca ``Ratelimited`` —
# ``chatbot.middleware.RatelimitedMiddleware`` przechwytuje exception
# i deleguje do ``chatbot.views.ratelimited`` → HTTP 429.
#
# ``django-axes`` jest niezależną warstwą (5 nieudanych prób per
# username+ip → lockout 1h) i przekierowuje na ``AXES_LOCKOUT_URL``.


@pytest.mark.django_db
class TestPlanerLoginViewRateLimit:
    """Rate-limit POST loginu po IP (20/h) — druga warstwa obok axes."""

    @pytest.fixture(autouse=True)
    def _clear_ratelimit_cache(self):
        """Wyzeruj cache ratelimitu między testami — inaczej kontaminacja."""
        cache.clear()
        yield
        cache.clear()

    def test_login_rate_limit_blocks_after_20_attempts(self, client):
        """Po 20 POSTach z tego samego IP — 21-szy daje 429 (lub 403/200 z block)."""
        login_url = reverse("accounts:login")
        # Pierwsze 20 — przechodzą do logiki view (axes/auth ich odrzuca,
        # ale ratelimit licznik jeszcze nie triggeruje block).
        for _ in range(20):
            client.post(login_url, {"username": "ghost", "password": "nope"})

        # 21-szy POST — ratelimit triggeruje ``Ratelimited`` exception,
        # middleware konwertuje na 429. Może też być 403 jeśli middleware
        # nie złapie, lub 200 jeśli ratelimit zliczył różnie.
        response = client.post(login_url, {"username": "ghost", "password": "nope"})
        assert response.status_code in (403, 429), (
            f"Spodziewano 403/429 po 21-szej próbie, dostano {response.status_code}"
        )


@pytest.mark.django_db
class TestAxesLockedView:
    """Strona pokazywana po lockout (``AXES_LOCKOUT_URL`` → ``/accounts/zablokowane/``)."""

    def test_locked_page_renders_polish_message(self, client):
        """GET ``/accounts/zablokowane/`` → 200 + polski komunikat."""
        response = client.get(reverse("accounts:locked"))
        assert response.status_code == 200
        body = response.content.decode().lower()
        assert "zablokowane" in body
        assert "administratorem" in body

    def test_locked_page_uses_base_template(self, client):
        """Strona musi extendować ``base.html`` (spójny UI, nav + footer)."""
        response = client.get(reverse("accounts:locked"))
        # Sprawdź obecność elementów base — np. footer "Milestone 3".
        assert b"Milestone 3" in response.content
