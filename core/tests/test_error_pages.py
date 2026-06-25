"""Testy custom error pages (404 + 500).

Custom templates ``templates/404.html`` / ``templates/500.html`` są używane
tylko gdy ``DEBUG=False``. W dev mode Django pokazuje swój własny ekran
techniczny. Override DEBUG na potrzeby testu.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
def test_404_uses_custom_template(client):
    """GET na nieistniejący URL → 404 z polskim komunikatem custom template."""
    response = client.get("/totally/does/not/exist/")
    assert response.status_code == 404
    body = response.content.decode("utf-8")
    assert "Nie znaleziono strony" in body
    assert "Planer Maszyn" in body  # baseline base.html branding


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
def test_404_contains_home_link(client):
    """Custom 404 musi zawierać link do strony głównej."""
    response = client.get("/nope/nope/")
    assert response.status_code == 404
    body = response.content.decode("utf-8")
    assert 'href="/"' in body or "Wróć na stronę główną" in body


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
def test_403_uses_custom_template(client):
    """Zalogowany użytkownik bez uprawnień → 403 z custom template."""
    user = get_user_model().objects.create_user("noperm403", password="secret-pw-123!")
    client.force_login(user)
    response = client.get(reverse("reservations:create"))
    assert response.status_code == 403
    body = response.content.decode("utf-8")
    assert "Brak uprawnień" in body
