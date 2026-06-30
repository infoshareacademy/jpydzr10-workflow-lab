"""Regresja stored-XSS na widoku mapy.

Piny mapy zawierają edytowalne przez personel pola tekstowe (nazwa maszyny,
adres, nazwa budowy). Wcześniej dane były wstrzykiwane przez ``{{ pins_json|safe }}``
w ``<script type="application/json">`` — wartość typu ``</script><img onerror=...>``
zamykała element script i wykonywała kod. Teraz używamy ``json_script``, które
escapuje ``< > &`` do ``\\u003C`` itd. Ten test pilnuje, że payload NIE wychodzi
dosłownie do HTML.
"""

from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.factories import UserFactory
from machines.factories import MachineFactory

pytestmark = pytest.mark.django_db

_PAYLOAD = "</script><img src=x onerror=alert(1)>"


# Blok ``pins-data`` renderuje się tylko gdy skonfigurowano klucz Google Maps
# (ścieżka podatna na XSS w produkcji). Ustawiamy go, by przetestować właściwy kod.
@override_settings(GOOGLE_MAPS_API_KEY="AIzaTestDummyKeyForXssRegression")
def test_machine_name_xss_is_escaped_on_map(client):
    MachineFactory(name=_PAYLOAD)
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("maps"))
    assert response.status_code == 200
    body = response.content.decode("utf-8")

    # Dosłowny payload (breakout) NIE może pojawić się w HTML.
    assert _PAYLOAD not in body
    # json_script escapuje "<" do < — dowód, że dane przeszły bezpieczną ścieżką.
    assert "\\u003C" in body or "\\u003c" in body
