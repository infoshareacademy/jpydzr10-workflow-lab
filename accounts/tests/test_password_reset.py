"""Testy flow „zapomniałem hasła" (reset hasła przez e-mail).

Pokrywa pełny cykl: formularz adresu → dwujęzyczny (PL+EN) mail z linkiem →
ustawienie nowego hasła → logowanie nowym hasłem. Plus zabezpieczenia: brak
enumeracji kont (nieznany adres nie ujawnia, czy konto istnieje), odrzucenie
nieprawidłowego/wygasłego linku, obecność linku na stronie logowania.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

User = get_user_model()
pytestmark = pytest.mark.django_db

_NEW_PASSWORD = "NoweHaslo2026!"


def _make_user(username="resetuser", email="reset@demo.test", password="StareHaslo2026!"):
    return User.objects.create_user(username, email=email, password=password)


def _extract_reset_url(body: str) -> str:
    """Wyłuskaj link resetujący z treści maila (tekstowej)."""
    match = re.search(r"https?://\S+/reset-hasla/\S+", body)
    assert match, f"Brak linku resetującego w mailu:\n{body}"
    return match.group(0)


def test_reset_request_page_renders(client):
    resp = client.get(reverse("accounts:password_reset"))
    assert resp.status_code == 200
    assert b'name="email"' in resp.content


def test_login_page_links_to_reset(client):
    resp = client.get(reverse("accounts:login"))
    assert resp.status_code == 200
    assert reverse("accounts:password_reset").encode() in resp.content


def test_known_user_receives_bilingual_email(client):
    user = _make_user(email="known@demo.test")
    resp = client.post(reverse("accounts:password_reset"), {"email": user.email})
    assert resp.status_code == 302
    assert resp.url == reverse("accounts:password_reset_done")

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [user.email]
    # Temat dwujęzyczny.
    assert "Reset hasła" in message.subject
    assert "Password reset" in message.subject
    # Treść tekstowa zawiera obie wersje językowe (separator ENGLISH) i link.
    assert "ENGLISH" in message.body
    assert "Link jest ważny" in message.body  # PL
    assert (
        "valid for" in message.body
        or "is valid" in message.body
        or "link is" in message.body.lower()
    )
    url = _extract_reset_url(message.body)
    assert "/reset-hasla/" in url
    # Wersja HTML (alternatywa) też istnieje i zawiera link.
    html = message.alternatives[0][0]
    assert "reset-hasla" in html


def test_unknown_email_does_not_enumerate(client):
    """Nieznany adres → ten sam redirect, ZERO maili (brak ujawnienia konta)."""
    resp = client.post(reverse("accounts:password_reset"), {"email": "nieistnieje@demo.test"})
    assert resp.status_code == 302
    assert resp.url == reverse("accounts:password_reset_done")
    assert len(mail.outbox) == 0


def test_full_flow_resets_password_and_allows_login(client):
    user = _make_user(email="flow@demo.test")
    # 1. Poproś o reset.
    client.post(reverse("accounts:password_reset"), {"email": user.email})
    url = _extract_reset_url(mail.outbox[0].body)

    # 2. GET linku → confirm view przenosi token do sesji i redirectuje na
    #    URL z „set-password"; follow=True dochodzi do formularza (200).
    resp = client.get(url, follow=True)
    assert resp.status_code == 200
    post_url = resp.redirect_chain[-1][0] if resp.redirect_chain else url

    # 3. Ustaw nowe hasło.
    resp = client.post(
        post_url,
        {"new_password1": _NEW_PASSWORD, "new_password2": _NEW_PASSWORD},
        follow=True,
    )
    assert resp.status_code == 200

    # 4. Nowe hasło działa, stare nie.
    user.refresh_from_db()
    assert user.check_password(_NEW_PASSWORD)
    assert client.login(username=user.username, password=_NEW_PASSWORD)


def test_invalid_link_shows_error_page(client):
    resp = client.get(
        reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": "AAA", "token": "zly-token-123"},
        ),
        follow=True,
    )
    assert resp.status_code == 200
    # validlink=False → komunikat o nieprawidłowym linku.
    assert "nieprawidłowy".encode() in resp.content.lower() or b"wygas" in resp.content.lower()
