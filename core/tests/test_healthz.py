"""Testy endpointu /healthz/ (DB ping + status code)."""

import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_returns_ok():
    """healthz powinien zwrócić 200 OK gdy DB działa."""
    client = Client()
    response = client.get("/healthz/")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["checks"]["database"] is True


@pytest.mark.django_db
def test_healthz_returns_json_content_type():
    """healthz powinien zwracać JSON content-type."""
    client = Client()
    response = client.get("/healthz/")
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_healthz_db_failure_returns_503(monkeypatch):
    """Wave 12: DB pad → 503 + ok=false (lines 33-39).

    Monkey-patch ``connection.cursor`` żeby rzucał wyjątek — view powinien
    złapać, logger.exception, zwrócić 503 bez leak raw exception.
    """
    import core.views as core_views

    class BrokenConnection:
        def cursor(self):
            raise RuntimeError("DB connection lost")

    monkeypatch.setattr(core_views, "connection", BrokenConnection())

    client = Client()
    response = client.get("/healthz/")
    assert response.status_code == 503
    data = response.json()
    assert data["ok"] is False
    assert data["checks"]["database"] is False
    # Brak leak'u raw exception string w response body
    assert "DB connection lost" not in response.content.decode("utf-8")
