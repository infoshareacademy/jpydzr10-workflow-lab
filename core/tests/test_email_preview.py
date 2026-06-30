"""Testy deweloperskiego podglądu maili (core.email_preview).

Sprawdzają trzy zabezpieczenia (staff-only, DEBUG-only, allowlista szablonów)
oraz poprawny render w obu językach.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

User = get_user_model()
pytestmark = pytest.mark.django_db

PREVIEW_URL = reverse("email_preview")


def _staff_client(client):
    """Loguje świeżo utworzonego użytkownika ze statusem staff."""
    user = User.objects.create_user("preview_staff", password="x", is_staff=True)
    client.force_login(user)
    return client


@override_settings(DEBUG=True)
def test_anonymous_is_redirected(client):
    response = client.get(PREVIEW_URL)
    # @staff_member_required przekierowuje na ekran logowania admina.
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@override_settings(DEBUG=True)
def test_non_staff_is_redirected(client):
    user = User.objects.create_user("plain", password="x", is_staff=False)
    client.force_login(user)
    response = client.get(PREVIEW_URL)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@override_settings(DEBUG=True)
def test_index_lists_templates(client):
    _staff_client(client)
    response = client.get(PREVIEW_URL)
    assert response.status_code == 200
    body = response.content.decode()
    # Spis zawiera linki do każdego znanego szablonu.
    assert "reservation_confirmed" in body
    assert "inspection_overdue" in body
    assert "password_reset" in body


@override_settings(DEBUG=True)
def test_renders_known_template_pl(client):
    _staff_client(client)
    response = client.get(PREVIEW_URL, {"template": "reservation_confirmed", "lang": "pl"})
    assert response.status_code == 200
    body = response.content.decode()
    assert "KOP-014" in body  # dane z przykładowego kontekstu
    assert "została potwierdzona" in body  # fraza PL
    assert "ENGLISH" in body  # separator z base_email.html


@override_settings(DEBUG=True)
def test_renders_known_template_en(client):
    _staff_client(client)
    response = client.get(PREVIEW_URL, {"template": "reservation_confirmed", "lang": "en"})
    assert response.status_code == 200
    body = response.content.decode()
    assert "KOP-014" in body
    assert "has been confirmed" in body  # fraza EN (tłumaczenie z katalogu)


@override_settings(DEBUG=True)
def test_inspection_template_renders_machine_list(client):
    _staff_client(client)
    response = client.get(PREVIEW_URL, {"template": "inspection_overdue"})
    assert response.status_code == 200
    body = response.content.decode()
    assert "WAL-003" in body  # druga maszyna z listy przykładowej


@override_settings(DEBUG=True)
def test_unknown_template_is_404_no_arbitrary_render(client):
    _staff_client(client)
    # Próba path traversal / nieznana nazwa — nie wolno renderować niczego spoza
    # allowlisty.
    for bad in ["../base", "base_email", "does_not_exist", "../../settings"]:
        response = client.get(PREVIEW_URL, {"template": bad})
        assert response.status_code == 404


@override_settings(DEBUG=False)
def test_debug_off_is_404_even_for_staff(client):
    _staff_client(client)
    response = client.get(PREVIEW_URL, {"template": "reservation_confirmed"})
    assert response.status_code == 404
