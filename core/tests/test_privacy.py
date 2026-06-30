"""Testy stron GDPR: polityka prywatności + baner ciasteczek."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_privacy_page_public_and_complete():
    """Polityka prywatności jest publiczna (bez logowania) i ma kluczowe sekcje."""
    resp = Client().get(reverse("core:privacy"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Polityka prywatności" in body
    assert "RODO" in body
    assert "Administrator danych" in body
    assert "Twoje prawa" in body
    assert "Ciasteczka" in body


def test_privacy_page_localized_to_english():
    client = Client()
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    resp = client.get(reverse("core:privacy"))
    body = resp.content.decode()
    assert "Privacy policy" in body
    assert "Your rights" in body


def test_cookie_banner_present_on_pages():
    """Baner informuje o ciasteczkach niezbędnych i linkuje do polityki."""
    resp = Client().get(reverse("core:privacy"))
    body = resp.content.decode()
    assert "planer-cookie-ack" in body  # localStorage flag baneru
    assert "niezbędnych ciasteczek" in body
