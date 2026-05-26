"""Testy custom error pages (404 + 500).

Custom templates ``templates/404.html`` / ``templates/500.html`` są używane
tylko gdy ``DEBUG=False``. W dev mode Django pokazuje swój własny ekran
techniczny. Override DEBUG na potrzeby testu.
"""

import pytest
from django.test import override_settings


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
