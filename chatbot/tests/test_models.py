"""Testy modeli :class:`Conversation` + :class:`Message`."""

from __future__ import annotations

import pytest

from chatbot.factories import (
    AssistantMessageFactory,
    ConversationFactory,
    ErrorMessageFactory,
    MessageFactory,
)
from chatbot.models import Conversation, Message


@pytest.mark.django_db
def test_conversation_str_contains_user_and_title():
    conv = ConversationFactory(title="Test pytanie o KOP-001")
    label = str(conv)
    assert "Konwersacja" in label
    assert "Test pytanie o KOP-001" in label
    assert conv.user.get_username() in label


@pytest.mark.django_db
def test_conversation_default_ordering_newest_first():
    a = ConversationFactory()
    b = ConversationFactory()
    qs = list(Conversation.objects.all())
    # newest_first = ostatnio utworzona jest pierwsza
    assert qs[0].pk == b.pk
    assert qs[1].pk == a.pk


@pytest.mark.django_db
def test_message_str_truncates_long_content():
    msg = MessageFactory(content="x" * 200)
    label = str(msg)
    # 60 znaków + "…"
    assert "xxxx" in label
    assert label.endswith("…")


@pytest.mark.django_db
def test_message_roles_have_polish_labels():
    user_msg = MessageFactory(role=Message.Role.USER)
    assistant_msg = AssistantMessageFactory()
    error_msg = ErrorMessageFactory()
    assert user_msg.get_role_display() == "Użytkownik"
    assert assistant_msg.get_role_display() == "Asystent"
    assert error_msg.get_role_display() == "Błąd"


@pytest.mark.django_db
def test_messages_ordered_by_created_at_ascending():
    conv = ConversationFactory()
    m1 = MessageFactory(conversation=conv, content="pierwsza")
    m2 = MessageFactory(conversation=conv, content="druga")
    qs = list(conv.messages.all())
    assert qs == [m1, m2]


@pytest.mark.django_db
def test_assistant_message_has_tokens():
    msg = AssistantMessageFactory()
    assert msg.tokens_used > 0


@pytest.mark.django_db
def test_conversation_cascade_deletes_messages():
    conv = ConversationFactory()
    MessageFactory(conversation=conv)
    MessageFactory(conversation=conv)
    assert Message.objects.filter(conversation=conv).count() == 2
    conv.delete()
    assert Message.objects.filter(conversation=conv.pk).count() == 0
