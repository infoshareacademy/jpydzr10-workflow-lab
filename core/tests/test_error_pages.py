"""Testy custom error pages (404 + 500).

Custom templates ``templates/404.html`` / ``templates/500.html`` są używane
tylko gdy ``DEBUG=False``. W dev mode Django pokazuje swój własny ekran
techniczny. Override DEBUG na potrzeby testu.
"""

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.views.defaults import server_error


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


@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
def test_500_uses_custom_template():
    """Handler 500 renderuje custom ``500.html`` z minimalnym kontekstem (bez wyjątku)."""
    request = RequestFactory().get("/boom/")
    response = server_error(request)
    assert response.status_code == 500
    body = response.content.decode("utf-8")
    assert "Wystąpił błąd serwera" in body
    assert "Planer Maszyn" in body


def test_maintenance_template_renders_standalone():
    """Strona przerwy technicznej (503) renderuje się samodzielnie (bez bazy/kontekstu)."""
    html = render_to_string("maintenance.html")
    assert "Przerwa techniczna" in html
    assert "maintenance" in html.lower()
