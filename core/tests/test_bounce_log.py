"""Testy fail-soft wysyłki maila: błąd SMTP nie wywraca akcji, tworzy BounceLog."""

from __future__ import annotations

import pytest

from core import mailing
from core.models import BounceLog

pytestmark = pytest.mark.django_db


def test_smtp_failure_records_bounce_per_recipient(monkeypatch):
    def boom(self):
        raise OSError("SMTP connection refused")

    monkeypatch.setattr(mailing.EmailMultiAlternatives, "send", boom)
    sent = mailing.send_bilingual_mail(
        "Temat testowy", "<p>x</p>", "x", ["a@demo.test", "b@demo.test"]
    )
    assert sent == 0
    assert BounceLog.objects.count() == 2
    bounce = BounceLog.objects.get(recipient="a@demo.test")
    assert bounce.subject == "Temat testowy"
    assert "SMTP connection refused" in bounce.error


def test_successful_send_creates_no_bounce(mailoutbox):
    sent = mailing.send_bilingual_mail("OK", "<p>x</p>", "x", ["ok@demo.test"])
    assert sent == 1
    assert BounceLog.objects.count() == 0
    assert len(mailoutbox) == 1


def test_no_recipients_no_bounce():
    assert mailing.send_bilingual_mail("Pusto", "<p>x</p>", "x", []) == 0
    assert BounceLog.objects.count() == 0
