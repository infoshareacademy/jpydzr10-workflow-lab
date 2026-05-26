"""Global search service — szuka po wszystkich kluczowych encjach.

Wave 14-D: prezentacja 14.06.2026 — Sebastian wymaga FULL GLOBAL SEARCH
w topbar. Wcześniej input był ``disabled`` z placeholderem "Milestone 3";
od teraz operator (np. magazynier dyżurny) wpisuje frazę i widzi natychmiast
hity ze wszystkich modułów:

* **Maszyny** — po ``uid``, ``name``, ``machine_type``, ``serial_number``,
  ``manufacturer``, ``model``.
* **Rezerwacje** — po ``person``, ``responsible_person``, ``address``,
  ``notes`` oraz dokładnym PK (``#123``).
* **Budowy** (ConstructionSite) — po ``project_number``, ``name``,
  ``address``, ``city``, ``client_name``.
* **Serwis** (ServiceRecord) — po ``description``, ``performed_by`` oraz
  dokładnym PK.

Service warstwy ma zero zależności od ``request`` / sesji — jest czystą
funkcją do testowania i może być wywoływana z chatbot tool-calls,
management command, lub CLI. View layer (``core.views.global_search_view``)
obudowuje go decoratorem ``@login_required`` + ``render``.

Zasady projektowe:

* **Min 2 znaki** — nie chcemy aktywować 5-table OR LIKE dla pojedynczej
  litery (kosztuje I/O, daje 100% szumu).
* **Limit per category** (domyślnie 5) — dropdown ma mieścić się w
  ``max-h-[28rem] overflow-y-auto``; pełna lista (>5) wymaga kliknięcia
  "Zobacz wszystkie wyniki →" na stronie /szukaj/.
* **Permission-aware** — anonim nie wywoła view (login_required), ale
  zwykły user (nie-staff, nie-superuser) widzi:
    - Maszyny tylko z ``perm machines.view_machine`` (przeważnie wszyscy),
    - Rezerwacje filtrowane po ``person ilike user.full_name`` (jego własne),
    - Budowy bez filtrowania (read-only listing dla wszystkich),
    - Serwis bez filtrowania (jak Budowy — dane operacyjne).
  Superuser / staff widzi WSZYSTKO bez filtra.
* **``select_related``** dla rezerwacji + serwisu — żeby ``r.machine.uid``
  w title nie generował N+1 (per kategoria limit 5 → bez fetcha to 5
  extra round-tripów).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q
from django.urls import reverse

# Heroicons (outline 24x24, stroke-width 1.5) jako string SVG markup —
# inline w template (klient nie potrzebuje icon-sprite). Wybór ikon
# konsekwentny z sidebar nav w base.html (wzorzec layoutu konsystentny z
# icon-style-consistent — używamy tej samej rodziny ikon).
ICON_MACHINES = (
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" '
    'viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" '
    'aria-hidden="true">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M8.25 18.75a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m3 0h6m-9 0H3.375a1.125 '
    "1.125 0 01-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 "
    "0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 00-3.213-9.193 "
    "2.056 2.056 0 00-1.58-.86H14.25M16.5 18.75h-2.25m0-11.177v-.958c0-.568-.422-1.048-.987-1.106a48.554 "
    "48.554 0 00-10.026 0 1.106 1.106 0 00-.987 1.106v7.635m12-6.677v6.677m0 "
    '4.5v-4.5m0 0h-12"/>'
    "</svg>"
)

ICON_RESERVATIONS = (
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" '
    'viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" '
    'aria-hidden="true">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 '
    "2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 "
    '18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5"/>'
    "</svg>"
)

ICON_SITES = (
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" '
    'viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" '
    'aria-hidden="true">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 '
    "3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 "
    '1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21"/>'
    "</svg>"
)

ICON_SERVICE = (
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" '
    'viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" '
    'aria-hidden="true">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M11.42 15.17 17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 '
    "15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 "
    "5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 "
    "1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 "
    "0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 "
    "2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 "
    "4.5v1.409l4.26 4.26m-1.745 1.437 1.745-1.437m6.615 8.206L15.75 "
    '15.75M4.867 19.125h.008v.008h-.008v-.008z"/>'
    "</svg>"
)

# Wartość poniżej której nie wykonujemy żadnego zapytania (3-literowe
# UID-y jak "M-1" muszą działać → próg 2, nie 3).
MIN_QUERY_LENGTH = 2

# Default limit per kategoria — dropdown UX (>5 = scroll cognitive overload).
DEFAULT_LIMIT = 5


@dataclass(frozen=True)
class SearchResult:
    """Pojedynczy hit z konkretnej encji.

    ``frozen=True`` — niezmienne, bezpieczne do hashowania jeśli kiedyś
    użyjemy ``set`` do deduplikacji (np. machine zwracana raz po UID i
    raz po name).
    """

    category: str  # "Maszyny" / "Rezerwacje" / "Budowy" / "Serwis"
    icon: str  # SVG markup (inline)
    title: str  # primary text (np. "KOP-001 — Koparka CAT 320")
    subtitle: str  # secondary text (np. "Dostępna · Magazyn")
    url: str  # link do detail page
    badge: str = field(default="")  # opcjonalny badge (np. typ maszyny)


def _normalize_query(query: str | None) -> str:
    """Trim + dół-case-safe — ``icontains`` jest case-insensitive na
    poziomie ORM, więc nie zmieniamy case'u sami, tylko strip.
    """
    return (query or "").strip()


def _can_see_all(user) -> bool:
    """Superuser lub staff widzi wszystkie encje bez ownership-filter."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def _user_full_name(user) -> str:
    """Bezpieczny full_name (ucięty whitespace) — jeśli pusty, fallback
    na ``username``. ``person`` w rezerwacji jest free-text, więc
    porównujemy ``icontains``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    full = (user.get_full_name() or "").strip()
    return full or (user.username or "")


# -----------------------------------------------------------------------------
# Per-kategoria search helpers — każdy zwraca ``list[SearchResult]``.
# -----------------------------------------------------------------------------


def _search_machines(query: str, user, limit: int) -> list[SearchResult]:
    """Search po Maszynach.

    Permission gate: brak ``machines.view_machine`` (lub anonimowy)
    → ``[]``. Większość ról w systemie ma ten perm; gate trzyma się
    Django-standardu (nie własne flagi). Staff / superuser zawsze widzi
    (parity z ``_can_see_all`` używanym w innych kategoriach).
    """
    from machines.models import Machine

    # Anonim / brak perm → bez kategorii.
    # Superuser ma has_perm zawsze True; ``is_staff`` jest naszą wewnętrzną
    # konwencją (parity z _can_see_all używanym w reservations/sites/service).
    if not user or not getattr(user, "is_authenticated", False):
        return []
    if not (_can_see_all(user) or user.has_perm("machines.view_machine")):
        # Zwykły user bez ``view_machine`` (rzadkie) nie zobaczy machine
        # hits, ale ZAUFANIE: nie ujawniamy że istnieją (no leakage).
        return []

    machines = Machine.objects.filter(
        Q(uid__icontains=query)
        | Q(name__icontains=query)
        | Q(machine_type__icontains=query)
        | Q(serial_number__icontains=query)
        | Q(manufacturer__icontains=query)
        | Q(model__icontains=query)
    ).order_by("uid")[:limit]

    results: list[SearchResult] = []
    for m in machines:
        status_label = m.get_status_display()
        location = m.location or "brak lokalizacji"
        results.append(
            SearchResult(
                category="Maszyny",
                icon=ICON_MACHINES,
                title=f"{m.uid} — {m.name}",
                subtitle=f"{status_label} · {location}",
                url=reverse("machines:detail", args=[m.uid]),
                badge=m.get_machine_type_display(),
            )
        )
    return results


def _search_reservations(query: str, user, limit: int) -> list[SearchResult]:
    """Search po Rezerwacjach.

    Permission filtering: zwykły user widzi tylko swoje (``person`` w
    rezerwacji to free-text, więc ``icontains user.full_name``). Staff /
    superuser widzi wszystkie. To jest pragmatyczny shim — model nie ma
    jeszcze FK do User (Milestone 3 zaplanowane), więc unikamy
    fałszywej iluzji "moje" vs "cudze" gdy ten sam imię i nazwisko może
    nie być unikalne, ale dla prezentacji 14.06.2026 wystarczy.
    """
    from reservations.models import Reservation

    if not user or not getattr(user, "is_authenticated", False):
        return []

    qs = Reservation.objects.select_related("machine", "site")

    # Filtr ownership dla non-staff.
    if not _can_see_all(user):
        full_name = _user_full_name(user)
        if full_name:
            qs = qs.filter(person__icontains=full_name)
        else:  # pragma: no cover — user bez full_name ani username (niemożliwe)
            return []

    # Próba: numeryczne query → exact PK match (#123 search).
    text_q = (
        Q(person__icontains=query)
        | Q(notes__icontains=query)
        | Q(responsible_person__icontains=query)
        | Q(address__icontains=query)
    )
    # Stripped # prefix dla "#123" → 123 (operator wpisuje #ID).
    stripped = query.lstrip("#")
    if stripped.isdigit():
        text_q = text_q | Q(pk=int(stripped))

    reservations = qs.filter(text_q).order_by("-created_at")[:limit]

    results: list[SearchResult] = []
    for r in reservations:
        status_label = r.get_status_display()
        machine_uid = r.machine.uid if r.machine_id else "—"
        results.append(
            SearchResult(
                category="Rezerwacje",
                icon=ICON_RESERVATIONS,
                title=f"Rezerwacja #{r.pk} — {r.person}",
                subtitle=f"{machine_uid} · {r.start_date}-{r.end_date} · {status_label}",
                url=reverse("reservations:detail", args=[r.pk]),
            )
        )
    return results


def _search_sites(query: str, user, limit: int) -> list[SearchResult]:
    """Search po Budowach (ConstructionSite).

    Listing jest read-only dla każdego zalogowanego usera (operatorzy
    często patrzą "co jest na BUD-2026-014" bez bycia ownerem). Brak
    własnego ownership-filter na poziomie modelu, więc i tu nie filtrujemy.
    """
    from reservations.models import ConstructionSite

    if not user or not getattr(user, "is_authenticated", False):
        return []

    sites = ConstructionSite.objects.filter(
        Q(project_number__icontains=query)
        | Q(name__icontains=query)
        | Q(address__icontains=query)
        | Q(city__icontains=query)
        | Q(client_name__icontains=query)
    ).order_by("-created_at")[:limit]

    results: list[SearchResult] = []
    for s in sites:
        status_label = s.get_status_display()
        address = s.address or "brak adresu"
        results.append(
            SearchResult(
                category="Budowy",
                icon=ICON_SITES,
                title=f"{s.project_number} — {s.name}",
                subtitle=f"{address} · {status_label}",
                url=reverse("reservations:site_detail", args=[s.pk]),
            )
        )
    return results


def _search_service(query: str, user, limit: int) -> list[SearchResult]:
    """Search po Serwisie (ServiceRecord)."""
    from service.models import ServiceRecord

    if not user or not getattr(user, "is_authenticated", False):
        return []

    text_q = Q(description__icontains=query) | Q(performed_by__icontains=query)
    stripped = query.lstrip("#")
    if stripped.isdigit():
        text_q = text_q | Q(pk=int(stripped))

    records = (
        ServiceRecord.objects.select_related("machine")
        .filter(text_q)
        .order_by("-performed_date")[:limit]
    )

    results: list[SearchResult] = []
    for r in records:
        machine_uid = r.machine.uid if r.machine_id else "—"
        performer = r.performed_by or "bez wykonawcy"
        record_type_label = r.get_record_type_display()
        results.append(
            SearchResult(
                category="Serwis",
                icon=ICON_SERVICE,
                title=f"#{r.pk} {machine_uid} — {record_type_label}",
                subtitle=f"{r.performed_date} · {performer} · {r.cost} PLN",
                url=reverse("service:detail", args=[r.pk]),
            )
        )
    return results


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def global_search(
    query: str | None,
    user,
    limit_per_category: int = DEFAULT_LIMIT,
) -> dict[str, list[SearchResult]]:
    """Search across all entities — main entrypoint.

    Returns ``dict[category_name -> list[SearchResult]]`` — kategorie bez
    hitów są pominięte (template renderuje tylko niepuste sekcje).

    Permission-aware: patrz docstring modułu.

    >>> global_search("", user)  # za krótkie → pusto
    {}
    >>> global_search("KOP-001", user_with_machine_perm)
    {'Maszyny': [SearchResult(...)]}
    """
    q = _normalize_query(query)
    if len(q) < MIN_QUERY_LENGTH:
        return {}

    results: dict[str, list[SearchResult]] = {}

    machines = _search_machines(q, user, limit_per_category)
    if machines:
        results["Maszyny"] = machines

    reservations = _search_reservations(q, user, limit_per_category)
    if reservations:
        results["Rezerwacje"] = reservations

    sites = _search_sites(q, user, limit_per_category)
    if sites:
        results["Budowy"] = sites

    service = _search_service(q, user, limit_per_category)
    if service:
        results["Serwis"] = service

    return results
