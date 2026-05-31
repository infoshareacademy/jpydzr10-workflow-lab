"""DoD checker dla filtrow timeline (/rezerwacje/timeline/?format=json).

Uruchomienie:
    uv run python manage.py shell < scripts/check_filters_dod.py

Co weryfikuje:
    1. Dla kazdej kategorii filtra (machine_type, status, inspection, sort,
       site, person, responsible) iteruje po wszystkich wartosciach,
       liczy ile machine_rows zwraca endpoint.
    2. Sumuje wyniki per-kategoria i sprawdza asercja sum == EXPECTED.
    3. Specjalny test (Bug period-vs-machines): ?period=week/2week/month
       z tym samym machine_type=koparka -> wszystkie zwracaja TE SAME maszyny
       (period filtruje BARS, nie machines).
    4. Cumulative filters regression (Bug 63): kombinacje 3 filtrow
       (machine_type + person + period) -> wszystkie aktywne, AND-owane.

Exit:
    0 - wszystkie asercje PASS
    1 - przynajmniej jedna asercja FAILED (szczegoly w stdout)

Skrypt jest read-only - tworzy tylko test_dod_admin (jesli nie ma superusera)
i loguje go w Client. Nie modyfikuje danych.
"""

from __future__ import annotations

import sys

from django.contrib.auth import get_user_model
from django.test import Client

from machines.models import Machine
from reservations.models import ConstructionSite, Reservation

User = get_user_model()

# ============================================================================
# Setup: superuser + zalogowany Client
# ============================================================================

admin = User.objects.filter(is_superuser=True).first()
if not admin:
    admin = User.objects.create_superuser(
        username="test_dod_admin",
        email="dod@example.local",
        password="DoDtest!2026XYZ",
    )
    print(f"Utworzono testowego superusera: {admin.username}")

client = Client()
client.force_login(admin)

# ============================================================================
# Stale i helpery
# ============================================================================

TIMELINE_URL = "/rezerwacje/timeline/"

# Total maszyn (excl Wycofana) - timeline domyslnie wyklucza WYCOFANA, ale
# explicit ?status=Wycofana nadpisuje (zob. TimelineView linia ~1020).
TOTAL_RESERVABLE = Machine.objects.exclude(status=Machine.Status.WYCOFANA).count()
TOTAL_ALL = Machine.objects.count()

print()
print("=" * 70)
print("  DoD Filter Checker - timeline endpoint")
print("=" * 70)
print(f"  Total maszyn (excl WYCOFANA): {TOTAL_RESERVABLE}")
print(f"  Total maszyn (ALL):           {TOTAL_ALL}")
print(f"  Endpoint:                     GET {TIMELINE_URL}?format=json")
print("=" * 70)


def count_rows(params: dict) -> int | str:
    """Wykonuje GET na timeline z paramsami, zwraca liczbe machine_rows.

    Uwaga: ``HTTP_HOST='localhost'`` jest potrzebne bo dev ALLOWED_HOSTS
    nie zawiera ``testserver`` (default Django Client) - bez tego dostajemy
    DisallowedHost 400.
    """
    qp = {**params, "format": "json"}
    response = client.get(TIMELINE_URL, qp, HTTP_HOST="localhost")
    if response.status_code != 200:
        return f"HTTP{response.status_code}"
    try:
        data = response.json()
    except ValueError:
        return "JSON_ERR"
    return len(data.get("machine_rows", []))


def section(title: str) -> None:
    print()
    print(f"--- {title} ---")


errors: list[str] = []


def assert_eq(actual, expected, label: str) -> None:
    """Asercja z roznym formatowaniem dla pass/fail."""
    if actual == expected:
        print(f"  OK     SUMA: {actual} EXPECTED {expected}  [{label}]")
    else:
        msg = f"FAIL  SUMA: {actual} EXPECTED {expected}  [{label}]"
        print(f"  {msg}")
        errors.append(msg)


# ============================================================================
# 1. machine_type - iteruj po wszystkich choices, sum musi byc TOTAL_RESERVABLE
# ============================================================================
section("machine_type (kazdy typ z Machine.Type)")
total = 0
for value, _label in Machine.Type.choices:
    count = count_rows({"machine_type": value})
    print(f"  machine_type={value!r:35} -> {count} maszyn")
    if isinstance(count, int):
        total += count
assert_eq(total, TOTAL_RESERVABLE, "sum(machine_type) == TOTAL_RESERVABLE")


# ============================================================================
# 2. status - iteruj po wszystkich choices. UWAGA: ?status=Wycofana nadpisuje
#    default exclude (TimelineView linia ~1020), wiec sum = TOTAL_ALL (z WYCOFANA).
# ============================================================================
section("status (kazdy status z Machine.Status, ?status=Wycofana liczy WYCOFANE)")
total = 0
for value, _label in Machine.Status.choices:
    count = count_rows({"status": value})
    print(f"  status={value!r:20} -> {count} maszyn")
    if isinstance(count, int):
        total += count
assert_eq(total, TOTAL_ALL, "sum(status) == TOTAL_ALL (z WYCOFANA)")


# ============================================================================
# 3. inspection - 4 buckety: ok/warning/overdue/unknown. NIE override'uje
#    exclude WYCOFANA, wiec sum = TOTAL_RESERVABLE.
# ============================================================================
section("inspection (ok / warning / overdue / unknown)")
total = 0
for value in ("ok", "warning", "overdue", "unknown"):
    count = count_rows({"inspection": value})
    print(f"  inspection={value!r:10} -> {count} maszyn")
    if isinstance(count, int):
        total += count
assert_eq(total, TOTAL_RESERVABLE, "sum(inspection) == TOTAL_RESERVABLE")


# ============================================================================
# 4. sort - nie filtruje, tylko sortuje. Wszystkie wartosci zwracaja TE SAME
#    liczby maszyn (= TOTAL_RESERVABLE), tylko inna kolejnosc.
# ============================================================================
section("sort (uid / inspection_asc / inspection_desc) - sort NIE filtruje")
counts: list[tuple[str, int | str]] = []
for value in ("uid", "inspection_asc", "inspection_desc"):
    count = count_rows({"sort": value})
    counts.append((value, count))
    print(f"  sort={value!r:18} -> {count} maszyn")
unique = {c for _, c in counts if isinstance(c, int)}
if len(unique) == 1 and TOTAL_RESERVABLE in unique:
    print(f"  OK     wszystkie sort zwracaja {TOTAL_RESERVABLE} maszyn (sort nie filtruje)")
else:
    msg = f"FAIL  sort wartosci roznia sie miedzy soba lub nie rowna {TOTAL_RESERVABLE}: {counts}"
    print(f"  {msg}")
    errors.append(msg)


# ============================================================================
# 5. site - filtruje BARS (rezerwacje), NIE machines. Liczba machine_rows
#    zawsze = TOTAL_RESERVABLE niezaleznie od ?site=BUD-X.
# ============================================================================
section("site (kazda ConstructionSite) - site filtruje BARS, NIE machine_rows")
sites = list(
    ConstructionSite.objects.values_list("project_number", flat=True).order_by("project_number")
)
print(f"  (testujemy {len(sites)} budow z bazy)")
all_match = True
for project_num in sites:
    count = count_rows({"site": project_num})
    marker = "OK" if count == TOTAL_RESERVABLE else "MISMATCH"
    print(f"  {marker:8} site={project_num!r:18} -> {count} machine_rows")
    if count != TOTAL_RESERVABLE:
        all_match = False
if all_match and sites:
    print(f"  OK     wszystkie site filtry zwracaja {TOTAL_RESERVABLE} machine_rows")
elif not sites:
    print("  SKIP   brak ConstructionSite w bazie")
else:
    msg = "FAIL  site filtry ZMIENIAJA liczbe machine_rows (powinny tylko bars)"
    print(f"  {msg}")
    errors.append(msg)


# ============================================================================
# 6. person - filtruje BARS. machine_rows zawsze = TOTAL_RESERVABLE.
#    Iterujemy po unique person z rezerwacji.
# ============================================================================
section("person (kazda unique osoba rezerwujaca) - person filtruje BARS, NIE machine_rows")
persons = list(
    Reservation.objects.exclude(person="")
    .values_list("person", flat=True)
    .distinct()
    .order_by("person")
)
# Limit do max 10 zeby output byl czytelny - reszta sumowana w tle.
sample = persons[:10]
print(f"  (testujemy sample {len(sample)} z {len(persons)} unique persons)")
all_match = True
for person in sample:
    count = count_rows({"person": person})
    marker = "OK" if count == TOTAL_RESERVABLE else "MISMATCH"
    print(f"  {marker:8} person={person!r:40} -> {count} machine_rows")
    if count != TOTAL_RESERVABLE:
        all_match = False
# Background sweep dla pozostalych (bez printowania)
for person in persons[10:]:
    count = count_rows({"person": person})
    if count != TOTAL_RESERVABLE:
        all_match = False
        print(f"  MISMATCH person={person!r:40} -> {count}")
if all_match and persons:
    print(
        f"  OK     wszystkie {len(persons)} person filtry zwracaja {TOTAL_RESERVABLE} machine_rows"
    )
elif not persons:
    print("  SKIP   brak unique person w rezerwacjach")
else:
    msg = "FAIL  person filtry ZMIENIAJA liczbe machine_rows (powinny tylko bars)"
    print(f"  {msg}")
    errors.append(msg)


# ============================================================================
# 7. responsible - jak person, filtruje BARS.
# ============================================================================
section("responsible (kazda unique osoba odpowiedzialna) - filtruje BARS")
responsibles = list(
    Reservation.objects.exclude(responsible_person="")
    .values_list("responsible_person", flat=True)
    .distinct()
    .order_by("responsible_person")
)
sample = responsibles[:10]
print(f"  (testujemy sample {len(sample)} z {len(responsibles)} unique responsibles)")
all_match = True
for resp in sample:
    count = count_rows({"responsible": resp})
    marker = "OK" if count == TOTAL_RESERVABLE else "MISMATCH"
    print(f"  {marker:8} responsible={resp!r:40} -> {count} machine_rows")
    if count != TOTAL_RESERVABLE:
        all_match = False
for resp in responsibles[10:]:
    count = count_rows({"responsible": resp})
    if count != TOTAL_RESERVABLE:
        all_match = False
        print(f"  MISMATCH responsible={resp!r:40} -> {count}")
if all_match and responsibles:
    print(f"  OK     wszystkie {len(responsibles)} responsible zwracaja {TOTAL_RESERVABLE}")
elif not responsibles:
    print("  SKIP   brak unique responsible_person w rezerwacjach")
else:
    msg = "FAIL  responsible ZMIENIA liczbe machine_rows (powinno tylko bars)"
    print(f"  {msg}")
    errors.append(msg)


# ============================================================================
# 8. SPECJALNY: period filtruje BARS (rezerwacje), NIE machines.
#    ?period=week + machine_type=koparka VS ?period=month + machine_type=koparka
#    -> obie powinny zwrocic TE SAME maszyny (5 koparek). Period zmienia tylko
#    zakres dat dla rezerwacji w bars.
# ============================================================================
section("period interaction (week/2week/month + machine_type=koparka)")
print("  Wszystkie 3 powinny zwrocic TE SAMA liczbe machine_rows (period nie filtruje machines):")
period_counts = {}
for period in ("week", "2week", "month"):
    count = count_rows({"period": period, "machine_type": "koparka"})
    period_counts[period] = count
    print(f"  period={period!r:8} machine_type=koparka -> {count} machine_rows")
unique = set(period_counts.values())
if len(unique) == 1:
    print(
        f"  OK     wszystkie 3 periods zwracaja {unique.pop()} (period filtruje BARS, nie machines)"
    )
else:
    msg = f"FAIL  period zmienia liczbe machine_rows: {period_counts}"
    print(f"  {msg}")
    errors.append(msg)


# ============================================================================
# 9. CUMULATIVE FILTERS regression (Bug 63):
#    ?machine_type=koparka & person=<X> & period=month -> wszystkie 3 aktywne.
#    Wynik <= count(machine_type=koparka). Asercja: wynik to liczba koparek,
#    bo person filtruje BARS (machines pozostaja).
# ============================================================================
section("cumulative filters (Bug 63 regression): machine_type AND person AND period")
sample_person = persons[0] if persons else None
if sample_person is None:
    print("  SKIP   brak person do testu cumulative")
else:
    base_koparka = count_rows({"machine_type": "koparka"})
    cum = count_rows(
        {
            "machine_type": "koparka",
            "person": sample_person,
            "period": "month",
        }
    )
    print(f"  base                                machine_type=koparka -> {base_koparka}")
    print(f"  cumulative  machine_type=koparka + person={sample_person!r} + period=month -> {cum}")
    if cum == base_koparka:
        print(f"  OK     cumulative zwraca {cum} (person filtruje BARS, NIE machines)")
    else:
        msg = f"FAIL  cumulative {cum} != base_koparka {base_koparka}"
        print(f"  {msg}")
        errors.append(msg)


# ============================================================================
# Raport koncowy + exit
# ============================================================================

print()
print("=" * 70)
if errors:
    print(f"  FAILED: {len(errors)} asercji nie przeszly:")
    for e in errors:
        print(f"    - {e}")
    print("=" * 70)
    sys.exit(1)
print("  OK  Wszystkie asercje PASS")
print("=" * 70)
sys.exit(0)
