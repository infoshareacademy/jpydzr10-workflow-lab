"""Testy context processora navigation.

``is_authenticated`` nie jest już dostarczane przez nasz context processor —
Django ``django.contrib.auth.context_processors.auth`` dostarcza ``user``
do każdego template'u, więc używamy ``{% if user.is_authenticated %}``
w ``base.html``.
"""

from django.test import RequestFactory

from core.context_processors import navigation


def _build_request(path: str = "/"):
    """Helper tworzący goły GET request — context processor nie czyta usera."""
    return RequestFactory().get(path)


def test_navigation_returns_current_path():
    """Context processor zwraca aktualny path requestu."""
    request = _build_request("/machines/")
    result = navigation(request)
    assert result["current_path"] == "/machines/"


def test_navigation_only_exposes_current_path():
    """Brak ``is_authenticated`` w kontekście — odpowiada za to Django auth processor."""
    request = _build_request("/")
    result = navigation(request)
    assert "is_authenticated" not in result
    assert set(result.keys()) == {"current_path"}
