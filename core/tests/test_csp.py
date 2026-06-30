"""Testy regresji Content-Security-Policy (strict nonce-based script-src).

M3: usunięto ``'unsafe-inline'`` ze ``script-src`` aplikacji — inline ``<script>``
mają nonce, a inline event-handlery przeniesiono na delegację zdarzeń w
``static/js/app.js`` (``data-confirm`` / ``data-autosubmit`` / ``data-history-back`` /
``data-row-href``). Panel ``/admin/`` (szablony zewnętrzne z inline ``on*``) dostaje
``'unsafe-inline'`` z powrotem przez ``core.middleware.AdminCspRelaxMiddleware``.

Te testy pilnują, by:
- aplikacja użytkownika NIE emitowała ``'unsafe-inline'`` w ``script-src`` (regresja
  bezpieczeństwa) i emitowała nonce + ``'unsafe-eval'`` (Alpine.js),
- panel ``/admin/`` zachował relaksację (inaczej filtry unfold by się sypały).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

CSP_HEADER = "Content-Security-Policy"


def _script_src(response) -> str:
    """Wyłuskuje dyrektywę ``script-src`` z nagłówka CSP odpowiedzi."""
    header = response.headers.get(CSP_HEADER, "")
    for directive in header.split(";"):
        directive = directive.strip()
        if directive.startswith("script-src "):
            return directive
    return ""


@pytest.mark.django_db
class TestApplicationCsp:
    """Front-end użytkownika = ścisły, oparty na nonce ``script-src``."""

    def test_script_src_has_no_unsafe_inline(self, client):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="csptest", password="pw-1234!Tajne")
        client.force_login(user)
        response = client.get(reverse("home"))
        assert response.status_code == 200
        script_src = _script_src(response)
        assert script_src, "Brak dyrektywy script-src w nagłówku CSP"
        assert "'unsafe-inline'" not in script_src

    def test_script_src_emits_nonce_and_keeps_unsafe_eval(self, client):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="csptest2", password="pw-1234!Tajne")
        client.force_login(user)
        response = client.get(reverse("home"))
        script_src = _script_src(response)
        # nonce pokrywa inline <script nonce="{{ CSP_NONCE }}">; bez niego (po usunięciu
        # unsafe-inline) wszystkie nasze inline skrypty by przestały działać.
        assert "'nonce-" in script_src
        # Alpine.js 3.x wymaga unsafe-eval (new Function w evaluatorach) — zostaje.
        assert "'unsafe-eval'" in script_src


@pytest.mark.django_db
class TestAdminCspRelaxation:
    """Panel admina zachowuje ``'unsafe-inline'`` (third-party inline handlery)."""

    def test_admin_script_src_keeps_unsafe_inline(self, client):
        user_model = get_user_model()
        admin = user_model.objects.create_superuser(
            username="cspadmin", password="pw-1234!Tajne", email="a@example.com"
        )
        client.force_login(admin)
        response = client.get("/admin/")
        # /admin/ przy zalogowanym superuserze = 200 (changelist dashboardu unfold).
        assert response.status_code == 200
        script_src = _script_src(response)
        assert "'unsafe-inline'" in script_src

    def test_app_page_not_relaxed_even_for_staff(self, client):
        """Relaksacja dotyczy WYŁĄCZNIE ścieżek /admin/, nie całej sesji staffa."""
        user_model = get_user_model()
        admin = user_model.objects.create_superuser(
            username="cspadmin2", password="pw-1234!Tajne", email="b@example.com"
        )
        client.force_login(admin)
        response = client.get(reverse("home"))
        script_src = _script_src(response)
        assert "'unsafe-inline'" not in script_src
