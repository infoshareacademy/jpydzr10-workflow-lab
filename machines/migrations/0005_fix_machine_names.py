"""Data migration — korekty gramatyczne nazw maszyn w katalogu.

Zmiany:

* ``Wyżka magazynowa`` -> ``Wyciąg magazynowy``
  - "wyżka" to kolokwializm budowlany; w słownikach języka polskiego
    (PWN, SJP) brak; "wyciąg magazynowy" to forma poprawna i jednoznaczna
    (winda towarowa do obsługi magazynu wysokiego składowania).

* ``Walec 1..N`` -> ``Walec drogowy 1..N``
  - doprecyzowanie kategorii: "walec" sam w sobie jest dwuznaczny
    (walec drogowy / ogrodowy / lekki / wibracyjny); obrazek katalogowy
    pokazuje tandem road roller, więc dodajemy "drogowy" dla spójności
    semantycznej.

Migracja jest idempotentna — drugie uruchomienie nie zmienia nic
(``filter(name=...)`` zwraca pusty queryset jeśli nazwy są już poprawione).
"""

from __future__ import annotations

from django.db import migrations


def fix_names(apps, schema_editor) -> None:
    """Zaktualizuj nazwy maszyn na poprawne gramatycznie / precyzyjne."""
    Machine = apps.get_model("machines", "Machine")

    # 1. Wyżka -> Wyciąg magazynowy (1 rekord, machine_type=inne)
    Machine.objects.filter(name="Wyżka magazynowa").update(name="Wyciąg magazynowy")

    # 2. Walec N -> Walec drogowy N (3 rekordy, machine_type=walec)
    for machine in Machine.objects.filter(machine_type="walec", name__startswith="Walec "):
        # Pomiń jeśli już ma "drogowy" w nazwie (idempotencja).
        if "drogowy" in machine.name:
            continue
        suffix = machine.name.removeprefix("Walec ").strip()
        if suffix.isdigit():
            machine.name = f"Walec drogowy {suffix}"
            machine.save(update_fields=["name"])


def revert_names(apps, schema_editor) -> None:
    """Cofnięcie zmian — przywróć poprzednie nazwy."""
    Machine = apps.get_model("machines", "Machine")

    Machine.objects.filter(name="Wyciąg magazynowy").update(name="Wyżka magazynowa")

    for machine in Machine.objects.filter(
        machine_type="walec", name__startswith="Walec drogowy "
    ):
        suffix = machine.name.removeprefix("Walec drogowy ").strip()
        if suffix.isdigit():
            machine.name = f"Walec {suffix}"
            machine.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [
        ("machines", "0004_historicalmachine_is_reservable_and_more"),
    ]

    operations = [
        migrations.RunPython(fix_names, revert_names),
    ]
