"""Step implementations for ``login_logout.feature``.

Pokrywa lukę z F7-B audytu — do tej pory mieliśmy tylko unit testy w
``accounts/tests/test_views.py``, brakowało end-to-end Gherkin scenariuszy
dla najbardziej krytycznego flow (login → praca → logout).

Konwencja:

* ``@given`` używa ``parsers.parse`` żeby placeholders w cudzysłowach
  ("magazynier_login") mapowały się na argumenty kroków,
* ``client`` (Django test client) jest fixture per-scenariusz (pytest-bdd
  re-używa pytest fixtures),
* ``context`` (dict) trzyma user/response między given/when/then —
  szczegóły patrz ``tests/bdd/conftest.py``.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from pytest_bdd import given, parsers, scenarios, then, when

from accounts.factories import UserFactory

scenarios("../features/login_logout.feature")


# ----------------------------------------------------------------------------
# GIVEN — seed
# ----------------------------------------------------------------------------


@given(
    parsers.parse('użytkownika "{username}" z hasłem "{password}"'),
    target_fixture="user",
)
def given_user(username: str, password: str):
    """Tworzy aktywnego usera z podanym hasłem (UserFactory + ``set_password``).

    ``UserFactory`` nie ustawia hasła (testy zwykle używają ``force_login``),
    więc dla scenariuszy testujących pełen flow login musimy zrobić to ręcznie.
    """
    user = UserFactory(username=username)
    user.set_password(password)
    user.save()
    return user


@given(
    parsers.parse('zalogowanego użytkownika "{username}"'),
    target_fixture="user",
)
def given_logged_in_user(username: str, client):
    """Logujemy usera bezpośrednio przez ``client.force_login`` (skrót)."""
    user = UserFactory(username=username)
    client.force_login(user)
    return user


# ----------------------------------------------------------------------------
# WHEN — action
# ----------------------------------------------------------------------------


@when("magazynier wchodzi na stronę logowania")
def when_open_login(client, context: dict):
    """GET na stronę loginu — sprawdza że renderuje się formularz."""
    context["response"] = client.get(reverse("accounts:login"))
    assert context["response"].status_code == 200


@when(parsers.parse('podaje login "{username}" i hasło "{password}"'))
@when(parsers.parse('magazynier podaje login "{username}" i hasło "{password}"'))
def when_post_credentials(client, context: dict, username: str, password: str):
    """POST z credentials — domyślnie redirect na ``LOGIN_REDIRECT_URL``."""
    context["response"] = client.post(
        reverse("accounts:login"),
        data={"username": username, "password": password},
    )


@when("magazynier wylogowuje się")
def when_logout(client, context: dict):
    """POST na logout (Django 5 wymaga POST dla LogoutView)."""
    context["response"] = client.post(reverse("accounts:logout"))


# ----------------------------------------------------------------------------
# THEN — assertion
# ----------------------------------------------------------------------------


@then("zostaje przekierowany na stronę główną")
def then_redirect_home(context: dict):
    """Po udanym loginie — 302 z ``Location`` wskazującym na home."""
    resp = context["response"]
    assert resp.status_code == 302
    assert resp["Location"] in (reverse("home"), "/")


@then("jest zalogowany")
def then_is_logged_in(client, user):
    """Sprawdzamy obecność sesji Django dla zalogowanego usera."""
    # ``_auth_user_id`` w session = user jest zalogowany.
    assert "_auth_user_id" in client.session
    assert int(client.session["_auth_user_id"]) == user.pk


@then("widzi błąd logowania")
def then_login_error(context: dict):
    """Niepowodzenie loginu — 200 z form errors (re-render)."""
    resp = context["response"]
    assert resp.status_code == 200
    # Django LoginView pokazuje generyczny błąd "username or password" w form.
    assert resp.context["form"].errors


@then("nie jest zalogowany")
def then_not_logged_in(client):
    """Brak ``_auth_user_id`` w session — anonimowy lub po logout."""
    assert "_auth_user_id" not in client.session


# Auto-mark all generated tests jako integration + django_db (DB + sessions).
pytestmark = [pytest.mark.integration, pytest.mark.django_db]
