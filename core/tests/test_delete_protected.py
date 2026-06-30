"""Testy przyjaznej odmowy usunięcia obiektów chronionych FK (PROTECT).

Rezerwacje/serwis FK do maszyny i rezerwacje FK do budowy są na ``PROTECT``
(brak cichego kasowania danych biznesowych). Bez obsługi ``ProtectedError``
widoki usuwania zwracały 500; teraz pokazują komunikat i nie kasują obiektu.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from machines.factories import MachineFactory
from machines.models import Machine
from reservations.factories import ConstructionSiteFactory, ReservationFactory
from reservations.models import ConstructionSite, Reservation

pytestmark = pytest.mark.django_db


def _admin():
    return get_user_model().objects.create_superuser("adminprot", "a@demo.test", "Planer2026!")


def test_delete_machine_with_reservation_is_refused(client):
    machine = MachineFactory()
    ReservationFactory(machine=machine)
    client.force_login(_admin())

    response = client.post(reverse("machines:delete", kwargs={"uid": machine.uid}))

    assert response.status_code == 302  # przyjazny redirect, NIE 500
    assert Machine.objects.filter(pk=machine.pk).exists()  # maszyna NADAL istnieje


def test_delete_site_with_closed_reservation_is_refused(client):
    site = ConstructionSiteFactory()
    ReservationFactory(machine=MachineFactory(), site=site, status=Reservation.Status.ZAKONCZONA)
    client.force_login(_admin())

    response = client.post(reverse("reservations:site_delete", kwargs={"pk": site.pk}))

    assert response.status_code == 302
    assert ConstructionSite.objects.filter(pk=site.pk).exists()  # budowa NADAL istnieje
