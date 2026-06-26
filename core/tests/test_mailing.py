"""Testy wspólnych narzędzi mailingu (core.mailing)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from accounts.models import EmployeeProfile
from core.mailing import build_bilingual_email, fleet_admin_recipients, send_bilingual_mail

User = get_user_model()
pytestmark = pytest.mark.django_db


def _admin(username, email):
    user = User.objects.create_user(username, password="x", email=email)
    user.profile.function = EmployeeProfile.Function.ADMIN
    user.profile.save()  # signal sync_groups → grupa "Administratorzy"
    return user


def test_send_bilingual_mail_no_recipients_returns_zero():
    assert send_bilingual_mail("temat", "<p>x</p>", "x", []) == 0
    assert send_bilingual_mail("temat", "<p>x</p>", "x", ["", None]) == 0


def test_fleet_admin_recipients_only_active_admins_with_email():
    _admin("a1", "admin1@demo.test")
    _admin("a2", "admin2@demo.test")
    # Admin bez maila — pomijany.
    _admin("a3", "")
    # Zwykły magazynier — nie jest adresatem alertów floty.
    mag = User.objects.create_user("mag", password="x", email="mag@demo.test")
    mag.profile.function = EmployeeProfile.Function.MAGAZYNIER
    mag.profile.save()

    recipients = fleet_admin_recipients()
    assert recipients == ["admin1@demo.test", "admin2@demo.test"]


def test_build_bilingual_email_has_pl_and_en_sections():
    machine = type("M", (), {"uid": "M-1", "name": "Koparka", "location": "Magazyn"})()
    html, text = build_bilingual_email("inspection_overdue", {"machines": [machine]})
    # Sekcje obu języków obecne w jednym mailu (nagłówek tabeli: PL "Maszyna" /
    # EN "Machine" — tłumaczenie istniejące w katalogu).
    assert "przeterminowany przegląd" in html  # PL (treść)
    assert "Maszyna" in html  # PL (nagłówek)
    assert "Machine" in html  # EN (nagłówek przetłumaczony)
    assert "ENGLISH" in html  # separator z base_email
    assert "M-1" in html
    assert "M-1" in text
    # Stopka z placeholderem wypisu (GDPR) obecna.
    assert "Unsubscribe" in html
