"""Test factories dla accounts module.

Single source of truth dla fixtures użytkowników w testach. Wszystkie testy
powinny używać tych factory zamiast surowego ``User.objects.create_user(...)``
— daje deterministyczne sequence ID (zero kolizji), Polish locale na fake
data i spójność z resztą sufity (machines/reservations factories też używają
``DjangoModelFactory``).

Konwencje:

* ``UserFactory`` — domyślnie produkuje aktywnego non-staff pracownika.
* ``AdminUserFactory`` — superuser dla testów admina (``is_staff=True``,
  ``is_superuser=True``).
* ``EmployeeProfileFactory`` — używamy gdy chcemy customowy ``function`` lub
  ``phone``; w normalnym flow profil jest auto-tworzony przez signal
  ``post_save`` na User (zob. ``accounts/signals.py``), więc starczy
  ``UserFactory()`` i potem ``user.profile``.
"""

from __future__ import annotations

import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from accounts.models import EmployeeProfile

User = get_user_model()


class UserFactory(DjangoModelFactory):
    """Baseline factory — produces an active, non-staff employee user.

    ``django_get_or_create`` na ``username`` chroni przed kolizjami gdy ten
    sam username pojawia się w dwóch miejscach (np. seed + test).
    """

    class Meta:
        model = User
        django_get_or_create = ("username",)
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"pracownik{n}")
    first_name = factory.Faker("first_name", locale="pl_PL")
    last_name = factory.Faker("last_name", locale="pl_PL")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.pl")
    is_active = True
    is_staff = False


class AdminUserFactory(UserFactory):
    """Superuser dla testów Django Admin (staff + superuser flags)."""

    username = factory.Sequence(lambda n: f"admin{n}")
    is_staff = True
    is_superuser = True


class EmployeeProfileFactory(DjangoModelFactory):
    """Factory dla :class:`EmployeeProfile`.

    Uwaga: signal ``create_employee_profile`` tworzy profil automatycznie przy
    pierwszym ``user.save()`` — używaj tego factory gdy potrzebujesz customowy
    ``function`` lub ``phone``, lub gdy chcesz utworzyć profil dla istniejącego
    usera bez signal flow (rzadko).
    """

    class Meta:
        model = EmployeeProfile

    user = factory.SubFactory(UserFactory)
    function = EmployeeProfile.Function.MAGAZYNIER
    # Numer telefonu w formacie E.164 z gwarancją unikalności (Sequence) — pole
    # ``phone`` jest UNIQUE i walidowane regexem E.164, więc losowy Faker
    # ("123-456-789", spacje) łamałby zarówno format jak i unikalność.
    phone = factory.Sequence(lambda n: f"+48600{n:06d}")
    is_active_employee = True
