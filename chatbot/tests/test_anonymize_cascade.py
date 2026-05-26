"""Testy cascade'u anonimizacji GDPR Art.17 → chatbot Message.content.

Gdy admin anonimizuje pracownika (``accounts.services.anonymize_employee``),
PII zapisane w ``chatbot.Message.content`` (rola ``user``) musi zostać
zastąpione tekstem ``[anonimizowano]``. Odpowiedzi asystenta (rola
``assistant``) i wiadomości systemowe/błędów zostają nietknięte — nie
zawierają PII użytkownika (LLM nie loguje user inputu w body odpowiedzi).

Test jest tu (chatbot), nie w accounts, bo to chatbot jest stroną
"konsumującą" cascade — accounts/services.py importuje
``chatbot.models`` lokalnie. Testy w chatbot dają lepszą lokalność
asercji dla autora wymiany.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from accounts.services import anonymize_employee, register_employee
from chatbot.models import Conversation, Message


@pytest.mark.django_db
def test_anonymize_employee_scrubs_user_messages_to_placeholder():
    """``USER``-role Message.content → ``[anonimizowano]`` po anonimizacji."""
    profile = register_employee(
        username="cascade1",
        email="cascade1@example.com",
        password="StrongP@ss!CC1",
    )
    conv = Conversation.objects.create(user=profile.user, title="Test PII")
    user_msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.USER,
        content="Zarezerwuj koparkę dla Tomka Nowaka, tel 600-100-200",
    )

    anonymize_employee(profile)

    user_msg.refresh_from_db()
    assert user_msg.content == "[anonimizowano]"


@pytest.mark.django_db
def test_anonymize_employee_keeps_assistant_messages_intact():
    """Assistant odpowiedzi zostają — nie zawierają PII użytkownika."""
    profile = register_employee(
        username="cascade2",
        email="cascade2@example.com",
        password="StrongP@ss!CC2",
    )
    conv = Conversation.objects.create(user=profile.user)
    assistant_msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.ASSISTANT,
        content="OK, zarezerwowałem KOP-001 na jutro.",
        tokens_used=42,
    )

    anonymize_employee(profile)

    assistant_msg.refresh_from_db()
    assert assistant_msg.content == "OK, zarezerwowałem KOP-001 na jutro."
    assert assistant_msg.tokens_used == 42


@pytest.mark.django_db
def test_anonymize_employee_keeps_system_and_error_messages_intact():
    """System/error messages też zostają — to metadata, nie PII użytkownika."""
    profile = register_employee(
        username="cascade3",
        email="cascade3@example.com",
        password="StrongP@ss!CC3",
    )
    conv = Conversation.objects.create(user=profile.user)
    system_msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.SYSTEM,
        content="Sesja rozpoczęta",
    )
    error_msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.ERROR,
        content="Brak klucza API",
    )

    anonymize_employee(profile)

    system_msg.refresh_from_db()
    error_msg.refresh_from_db()
    assert system_msg.content == "Sesja rozpoczęta"
    assert error_msg.content == "Brak klucza API"


@pytest.mark.django_db
def test_anonymize_employee_scrubs_across_multiple_conversations():
    """Cascade obejmuje WSZYSTKIE konwersacje danego usera, nie tylko jedną."""
    profile = register_employee(
        username="cascade4",
        email="cascade4@example.com",
        password="StrongP@ss!CC4",
    )
    conv1 = Conversation.objects.create(user=profile.user, title="Conv 1")
    conv2 = Conversation.objects.create(user=profile.user, title="Conv 2")
    msg1 = Message.objects.create(
        conversation=conv1,
        role=Message.Role.USER,
        content="PII Tomka",
    )
    msg2 = Message.objects.create(
        conversation=conv2,
        role=Message.Role.USER,
        content="PII Anny",
    )

    anonymize_employee(profile)

    msg1.refresh_from_db()
    msg2.refresh_from_db()
    assert msg1.content == "[anonimizowano]"
    assert msg2.content == "[anonimizowano]"


@pytest.mark.django_db
def test_anonymize_employee_does_not_touch_other_users_messages():
    """Cascade scope'owany do anonimizowanego usera — cudza historia zostaje."""
    user_model = get_user_model()
    other_user = user_model.objects.create_user(
        username="other-user",
        password="OtherP@ss!1",
    )
    other_conv = Conversation.objects.create(user=other_user, title="Cudza")
    other_msg = Message.objects.create(
        conversation=other_conv,
        role=Message.Role.USER,
        content="Inna treść PII",
    )

    profile = register_employee(
        username="cascade5",
        email="cascade5@example.com",
        password="StrongP@ss!CC5",
    )
    own_conv = Conversation.objects.create(user=profile.user)
    Message.objects.create(
        conversation=own_conv,
        role=Message.Role.USER,
        content="Własne PII",
    )

    anonymize_employee(profile)

    other_msg.refresh_from_db()
    # Cudza wiadomość NIE została ruszona.
    assert other_msg.content == "Inna treść PII"


@pytest.mark.django_db
def test_anonymize_employee_no_conversations_does_not_crash():
    """Brak konwersacji u usera — cascade no-op, brak wyjątku."""
    profile = register_employee(
        username="cascade6",
        email="cascade6@example.com",
        password="StrongP@ss!CC6",
    )
    # Bez Conversation.create — pusto.

    # Nie powinno rzucić.
    anonymize_employee(profile)
    profile.refresh_from_db()
    assert profile.is_anonymized is True
