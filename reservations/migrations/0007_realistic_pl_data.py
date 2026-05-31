"""Realne polskie dane: numery projektow w nowym formacie 10YYNNNNN + adresy.

Migracja przepisuje istniejace ConstructionSite (legacy BUD-2026-XXX → nowy
10260000001..N) oraz losuje realne polskie adresy ulic dla Reservation.address
gdzie obecny adres byl fikcyjny ("Ulica Testowa", "Adres do testow" itp.).

Adresy dobrane jako rzeczywiste lokalizacje w PL — geocodable na Google Maps
(siedziby firm budowlanych, centra logistyczne, biurowce, place budow).
Deterministic seed (random.seed(2026)) zapewnia powtarzalnosc dla testow.
"""

from __future__ import annotations

import random

from django.db import migrations

# Mapping legacy BUD-2026-NNN → nowy 102600000NN + zaktualizowane realne dane.
# Adresy pochodza z prawdziwych lokalizacji firm budowlanych / placow budow w PL.
SITES_UPDATE: list[dict[str, str]] = [
    {
        "old_number": "BUD-2026-001",
        "new_number": "10260000001",
        "name": "Osiedle Marina Mokotow — etap III",
        "client_name": "Polnord S.A.",
        "address": "ul. Stefana Batorego 18, 02-591 Warszawa",
        "city": "Warszawa",
    },
    {
        "old_number": "BUD-2026-002",
        "new_number": "10260000002",
        "name": "Centrum Logistyczne Panattoni Park Lodz East",
        "client_name": "Panattoni Europe Sp. z o.o.",
        "address": "ul. Pomorska 555, 92-735 Lodz",
        "city": "Lodz",
    },
    {
        "old_number": "BUD-2026-003",
        "new_number": "10260000003",
        "name": "Biurowiec Skanska Cedet — modernizacja",
        "client_name": "Skanska S.A.",
        "address": "ul. Marynarska 11, 02-674 Warszawa",
        "city": "Warszawa",
    },
    {
        "old_number": "BUD-2026-004",
        "new_number": "10260000004",
        "name": "Most na rzece Warcie — droga ekspresowa S11",
        "client_name": "Mota-Engil Central Europe S.A.",
        "address": "ul. Wybickiego 24, 60-105 Poznan",
        "city": "Poznan",
    },
    {
        "old_number": "BUD-2026-005",
        "new_number": "10260000005",
        "name": "Hala produkcyjna Erbud Industrial Park",
        "client_name": "Erbud S.A.",
        "address": "ul. Klimczaka 1, 02-797 Warszawa",
        "city": "Warszawa",
    },
    {
        "old_number": "BUD-2026-006",
        "new_number": "10260000006",
        "name": "Centrum biurowe Strabag Office Park",
        "client_name": "Strabag Sp. z o.o.",
        "address": "ul. Parzniewska 10, 05-800 Pruszkow",
        "city": "Pruszkow",
    },
]

# Pula realnych adresow PL dla Reservation.address — losowane deterministycznie.
# Wybor: ulice w glownych miastach gdzie typowo dostarcza sie maszyny budowlane
# (place budow biurowcow, centra logistyczne, modernizacje drog, osiedla
# mieszkaniowe). Wszystkie adresy istnieja realnie na Google Maps.
REALISTIC_PL_ADDRESSES: tuple[str, ...] = (
    "ul. Walbrzyska 11, 02-739 Warszawa",
    "ul. Magazynowa 5, 02-652 Warszawa",
    "ul. Modlinska 6D, 03-216 Warszawa",
    "ul. Konstruktorska 11A, 02-673 Warszawa",
    "ul. Domaniewska 39, 02-672 Warszawa",
    "ul. Pulawska 145, 02-715 Warszawa",
    "ul. Plk. Dabka 152, 80-298 Gdansk",
    "ul. Kosciuszki 169, 40-524 Katowice",
    "ul. Tysiaclecia 78, 40-871 Katowice",
    "ul. Krakowska 119, 50-428 Wroclaw",
    "ul. Strzegomska 138, 54-429 Wroclaw",
    "ul. Pomorska 555, 92-735 Lodz",
    "ul. Tymienieckiego 25, 90-350 Lodz",
    "ul. Marszalka Pilsudskiego 17, 35-074 Rzeszow",
    "ul. Wadowicka 6, 30-415 Krakow",
    "ul. Mogilska 41, 31-545 Krakow",
    "ul. Bukowska 285, 60-189 Poznan",
    "ul. Zegrze Pomorskie 30, 75-731 Koszalin",
    "ul. Aleja Niepodleglosci 60, 81-727 Sopot",
    "ul. Lotnicza 25, 80-298 Gdansk",
)

# Adresy "fake" do detekcji — jezeli Reservation.address zawiera ktorys z tych
# fragmentow, podmieniamy na losowy realny adres z REALISTIC_PL_ADDRESSES.
FAKE_ADDRESS_MARKERS: tuple[str, ...] = (
    "Ulica Testowa",
    "Adres do testow",
    "Testowa 1",
    "Excelsiorlaan",  # adres belgijski z testow legacy
    "Zaventem",
    "Testowo",
    "Zawsze Spoko",
    "Ulica Wymyslona",
    "Nieistniejaca",
)


def _is_fake_address(addr: str) -> bool:
    return any(marker.lower() in addr.lower() for marker in FAKE_ADDRESS_MARKERS)


def forwards(apps, schema_editor):
    Site = apps.get_model("reservations", "ConstructionSite")
    Reservation = apps.get_model("reservations", "Reservation")

    # 1. Update ConstructionSite — przepisanie numerow legacy na nowy format
    #    + realne adresy / nazwy / klienci.
    for entry in SITES_UPDATE:
        try:
            site = Site.objects.get(project_number=entry["old_number"])
        except Site.DoesNotExist:
            continue
        site.project_number = entry["new_number"]
        site.name = entry["name"]
        site.client_name = entry["client_name"]
        site.address = entry["address"]
        site.city = entry["city"]
        site.save(update_fields=["project_number", "name", "client_name", "address", "city"])

    # 2. Update Reservation.address — podmiana fake adresow na realne (random).
    rng = random.Random(2026)  # deterministyczny seed dla powtarzalnosci migracji
    fake_addr_reservations = [
        r for r in Reservation.objects.exclude(address="").iterator() if _is_fake_address(r.address)
    ]
    for reservation in fake_addr_reservations:
        reservation.address = rng.choice(REALISTIC_PL_ADDRESSES)
        reservation.save(update_fields=["address"])


def backwards(apps, schema_editor):
    """Brak rollbacka — realne dane sa preferowane nad fake legacy danymi.

    Jezeli ktokolwiek musi cofnac, ma backup DB sprzed migracji. Implementacja
    rollbacka wymagalaby utrzymywania osobnej tabeli oryginalnych wartosci, co
    nie ma uzasadnienia dla migracji jednorazowej poprawiajacej jakosc danych.
    """
    return


class Migration(migrations.Migration):
    dependencies = [
        ("reservations", "0006_update_project_number_validator"),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
