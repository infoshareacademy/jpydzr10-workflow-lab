"""Fabryki factory_boy dla modeli chatbota.

Lekkie fixtury używane przez testy (rzadko przez seed — chat history powstaje
naturalnie w trakcie korzystania z aplikacji). Konwencja zgodna z pozostałymi
appkami: ``DjangoModelFactory`` + ``Faker(locale='pl_PL')`` dla treści.
"""

from __future__ import annotations

import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory
from factory.faker import Faker

from .models import Conversation, Message


class _UserFactory(DjangoModelFactory):
    """Minimalna fabryka usera — używana wyłącznie wewnątrz tego modułu.

    Nie eksportujemy jej (start z ``_``) bo w prawdziwym kodzie testowym
    korzystamy z fixture ``user`` z conftesta — fabryka jest tylko fallbackiem
    gdy konwersacja jest tworzona bez explicit user."""

    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"chat_user_{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.test")


class ConversationFactory(DjangoModelFactory):
    """Konwersacja z auto-generowanym tytułem i przypisanym userem."""

    class Meta:
        model = Conversation

    user = factory.SubFactory(_UserFactory)
    title = Faker("sentence", nb_words=6, locale="pl_PL")
    is_archived = False


class MessageFactory(DjangoModelFactory):
    """Wiadomość — domyślnie pytanie usera w nowej konwersacji."""

    class Meta:
        model = Message

    conversation = factory.SubFactory(ConversationFactory)
    role = Message.Role.USER
    content = Faker("sentence", nb_words=10, locale="pl_PL")
    tokens_used = 0


class AssistantMessageFactory(MessageFactory):
    """Odpowiedź asystenta — z niezerową liczbą tokenów."""

    role = Message.Role.ASSISTANT
    tokens_used = factory.Faker("random_int", min=50, max=500)


class ErrorMessageFactory(MessageFactory):
    """Wiadomość błędu (np. brak API key, timeout agenta)."""

    role = Message.Role.ERROR
    content = "Wystąpił błąd asystenta."
    tokens_used = 0
