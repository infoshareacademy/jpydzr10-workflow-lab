"""Testy dostępności (a11y, WCAG 2.1 AA) — niezmienniki renderowanego HTML.

Definition of Done Task 2.3.A: aplikacja ma spełniać podstawowe wymagania
WCAG 2.1 AA. Te testy weryfikują maszynowo-sprawdzalne niezmienniki na
faktycznie wyrenderowanych stronach (Django test ``client``) oraz na
serwowanym CSS (``static/css/custom.css``):

* bypass-blocks (WCAG 2.4.1) — link „przejdź do treści" + cel ``#main-content``,
* respektowanie ``prefers-reduced-motion`` (WCAG 2.3.3) w CSS,
* widoczny focus ring na elementach interaktywnych (WCAG 2.4.7),
* dokładnie jeden ``<h1>`` na stronę (hierarchia nagłówków, WCAG 1.3.1),
* etykiety ``<label for=...>`` powiązane z polami formularza (WCAG 1.3.1 / 3.3.2),
* dekoracyjne SVG oznaczone ``aria-hidden="true"`` (WCAG 1.1.1),
* nawigacja z ``aria-label`` (WCAG 1.3.1),
* ``<html lang=...>`` ustawiony (WCAG 3.1.1).

Strony testowe:
* login (``accounts:login``) — dostępna anonimowo,
* dashboard (``home``) — wymaga logowania (``login_required``);
  2FA jest pominięte w testach (``OTP_TESTING_BYPASS=True`` w settings/test).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _login_html(client) -> str:
    """Zwraca wyrenderowany HTML strony logowania (dostępnej anonimowo)."""
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    return response.content.decode("utf-8")


def _dashboard_html(client) -> str:
    """Loguje świeżego użytkownika i zwraca HTML dashboardu (``home``)."""
    user = get_user_model().objects.create_user(username="a11y_user", password="a11y-pw-9912!")
    client.force_login(user)
    response = client.get(reverse("home"))
    assert response.status_code == 200
    return response.content.decode("utf-8")


def _custom_css() -> str:
    """Czyta serwowany arkusz ``static/css/custom.css`` ze źródła statycznego."""
    css_path = Path(settings.STATICFILES_DIRS[0]) / "css" / "custom.css"
    assert css_path.exists(), f"Brak pliku CSS: {css_path}"
    return css_path.read_text(encoding="utf-8")


def test_skip_link_present_on_logged_in_page(client):
    """WCAG 2.4.1 — link „przejdź do treści" + cel ``#main-content`` na stronie."""
    html = _dashboard_html(client)
    assert 'href="#main-content"' in html, "Brak skip linka do treści głównej."
    assert 'id="main-content"' in html, "Brak celu skip linka (#main-content)."


def test_prefers_reduced_motion_rule_in_css():
    """WCAG 2.3.3 — serwowany CSS respektuje ``prefers-reduced-motion``."""
    css = _custom_css()
    assert "prefers-reduced-motion" in css, "Brak reguły prefers-reduced-motion w custom.css."
    # Reguła musi faktycznie skracać animacje/przejścia, nie być pustym blokiem.
    assert "animation-duration" in css or "transition-duration" in css


def test_focus_visible_ring_on_interactive_elements(client):
    """WCAG 2.4.7 — elementy interaktywne mają widoczny focus ring."""
    html = _dashboard_html(client)
    assert "focus-visible:ring" in html, (
        "Brak utility focus-visible:ring na elementach interaktywnych."
    )


def test_login_page_has_exactly_one_h1(client):
    """WCAG 1.3.1 — strona logowania ma dokładnie jeden nagłówek ``<h1>``."""
    html = _login_html(client)
    assert html.count("<h1") == 1, "Strona logowania musi mieć dokładnie jeden <h1>."


def test_dashboard_has_exactly_one_h1(client):
    """WCAG 1.3.1 — dashboard ma dokładnie jeden nagłówek ``<h1>``."""
    html = _dashboard_html(client)
    assert html.count("<h1") == 1, "Dashboard musi mieć dokładnie jeden <h1>."


def test_login_inputs_have_associated_labels(client):
    """WCAG 1.3.1 / 3.3.2 — pola logowania mają powiązane ``<label for=...>``."""
    html = _login_html(client)
    # Domyślne id Django dla AuthenticationForm: id_username / id_password.
    for field_id in ("id_username", "id_password"):
        assert f'id="{field_id}"' in html, f"Brak inputu o id={field_id}."
        assert f'for="{field_id}"' in html, f"Brak <label for={field_id}>."


def test_decorative_svgs_are_aria_hidden(client):
    """WCAG 1.1.1 — dekoracyjne ikony SVG są oznaczone ``aria-hidden="true"``."""
    html = _login_html(client)
    assert 'aria-hidden="true"' in html, 'Dekoracyjne SVG powinny mieć aria-hidden="true".'


def test_navigation_has_aria_label(client):
    """WCAG 1.3.1 — nawigacja jest opisana atrybutem ``aria-label``."""
    html = _dashboard_html(client)
    assert "aria-label=" in html, "Brak aria-label w nawigacji."
    # Sidebar (główna nawigacja) ma jawny aria-label.
    assert 'id="sidebar"' in html


def test_html_lang_attribute_set(client):
    """WCAG 3.1.1 — element ``<html>`` deklaruje atrybut ``lang``."""
    html = _dashboard_html(client)
    assert "<html lang=" in html, "Element <html> musi mieć atrybut lang."
