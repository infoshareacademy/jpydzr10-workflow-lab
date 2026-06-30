"""Testy rezygnacji z nieobowiązkowych maili (opt-out) + strony preferencji.

Pokrywa: podpisany token „wypisz się" (round-trip, odporność na manipulację),
``is_opted_out``, oraz widok ``email_preferences_view`` (dostęp tokenem bez
logowania, zapis preferencji, nieprawidłowy token, wymóg logowania bez tokenu).
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from accounts.factories import UserFactory
from core.email_optout import (
    EmailCategory,
    is_opted_out,
    make_unsubscribe_token,
    parse_unsubscribe_token,
    unsubscribe_url_for,
)

pytestmark = pytest.mark.django_db

URL = reverse("accounts:email_preferences")


def test_token_round_trip():
    token = make_unsubscribe_token(42, EmailCategory.REMINDERS)
    assert parse_unsubscribe_token(token) == (42, EmailCategory.REMINDERS)


def test_tampered_token_rejected():
    token = make_unsubscribe_token(7, EmailCategory.INSPECTIONS)
    assert parse_unsubscribe_token(token + "x") is None
    assert parse_unsubscribe_token("garbage") is None


def test_unknown_category_in_token_rejected():
    token = make_unsubscribe_token(7, "nieistniejaca-kategoria")
    assert parse_unsubscribe_token(token) is None


def test_is_opted_out_reads_profile():
    user = UserFactory()
    assert is_opted_out(user, EmailCategory.REMINDERS) is False
    user.profile.email_opt_outs = [EmailCategory.REMINDERS]
    user.profile.save(update_fields=["email_opt_outs"])
    assert is_opted_out(user, EmailCategory.REMINDERS) is True
    assert is_opted_out(user, EmailCategory.INSPECTIONS) is False


def test_unsubscribe_url_contains_token_and_path():
    user = UserFactory()
    url = unsubscribe_url_for(user, EmailCategory.REMINDERS)
    assert reverse("accounts:email_preferences") in url
    assert "token=" in url


def test_view_with_valid_token_renders_for_anonymous(client):
    user = UserFactory()
    token = make_unsubscribe_token(user.pk, EmailCategory.REMINDERS)
    resp = client.get(URL, {"token": token})
    assert resp.status_code == 200
    # Obie kategorie widoczne jako pozycje do zarządzania.
    assert b"cat_reminders" in resp.content
    assert b"cat_inspections" in resp.content


def test_view_post_unsubscribes_category(client):
    user = UserFactory()
    token = make_unsubscribe_token(user.pk, EmailCategory.REMINDERS)
    # Zaznaczone tylko inspections → rezygnacja z reminders.
    resp = client.post(URL, {"token": token, "cat_inspections": "on"})
    assert resp.status_code == 302
    user.profile.refresh_from_db()
    assert EmailCategory.REMINDERS in user.profile.email_opt_outs
    assert EmailCategory.INSPECTIONS not in user.profile.email_opt_outs


def test_view_post_can_resubscribe(client):
    user = UserFactory()
    user.profile.email_opt_outs = [EmailCategory.REMINDERS, EmailCategory.INSPECTIONS]
    user.profile.save(update_fields=["email_opt_outs"])
    token = make_unsubscribe_token(user.pk, EmailCategory.REMINDERS)
    # Oba zaznaczone → ponowna subskrypcja obu.
    client.post(URL, {"token": token, "cat_reminders": "on", "cat_inspections": "on"})
    user.profile.refresh_from_db()
    assert user.profile.email_opt_outs == []


def test_view_invalid_token_shows_error(client):
    resp = client.get(URL, {"token": "zepsuty-token"})
    assert resp.status_code == 200
    assert "nieprawidłowy".encode() in resp.content.lower()


def test_view_requires_token_or_login(client):
    resp = client.get(URL)
    assert resp.status_code == 302
    assert reverse("accounts:login") in resp.url


def test_view_logged_in_user_manages_own(client):
    user = UserFactory()
    client.force_login(user)
    resp = client.get(URL)
    assert resp.status_code == 200
    assert b"cat_reminders" in resp.content
