"""Widoki aplikacji core (healthz endpoint + home dashboard + global search).

Home view został tu przeniesiony z ``planer_config/urls.py`` (Wave 4 P0)
żeby dodać ``@login_required`` — wcześniej anonymous miał wgląd w listę
rezerwacji z polem ``person`` (PII), co naruszało GDPR.

Wave 14-D (prezentacja 14.06.2026): ``global_search_view`` aktywuje
disabled-od-M1 input w topbar, robi typeahead przez HTMX (``request.htmx``
→ partial dropdown) oraz pełną stronę ``/szukaj/?q=...`` jako fallback
gdy operator naciśnie Enter zamiast klikać w wynik dropdownu.
"""

from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import connection
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit

from core.search import global_search


def privacy_policy(request):
    """Strona polityki prywatności (RODO/GDPR) — dwujęzyczna przez {% trans %}.

    Publiczna (bez logowania) — informuje o administratorze danych, zakresie
    przetwarzania, podstawach prawnych, prawach osoby i okresie retencji.
    """
    return render(request, "core/privacy.html")


def healthz(request):
    """Health check endpoint — sprawdza dostępność DB poprzez SELECT 1.

    Zwraca:
    - 200 OK + {"ok": true, "checks": {"database": true}} gdy wszystko działa.
    - 503 Service Unavailable + {"ok": false, "checks": {...}} gdy DB padła.

    Używane przez load balancery / uptime checki / docker healthcheck.
    """
    checks = {}
    db_ok = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception:
        # M1 fix: NIE leakuj raw exception string do public endpoint —
        # psycopg OperationalError może zawierać DB hostname, port, username,
        # auth-failure details. Pełny stack trace tylko do server-side log.
        import logging

        logging.getLogger("core").exception("Healthz DB check failed")
    checks["database"] = db_ok
    status = 200 if db_ok else 503
    return JsonResponse({"ok": db_ok, "checks": checks}, status=status)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def debug_boom(request):
    """Celowo rzuca wyjątek — do weryfikacji integracji z GlitchTip.

    Dostępny wyłącznie dla zalogowanego administratora (i poza listą wymuszenia
    2FA). Służy jednorazowemu potwierdzeniu, że nieobsłużone wyjątki trafiają do
    zgrupowanych zgłoszeń w GlitchTip.

    ``@login_required`` (defense-in-depth) jawnie wymusza zalogowanie — nie
    polegamy wyłącznie na tym, że ``user_passes_test`` przekieruje anonima. Nie
    tworzymy też cichej zależności od pozycji ``/debug/boom`` na liście wyjątków
    od wymuszenia 2FA w ``TwoFactorEnforcementMiddleware``.
    """
    raise RuntimeError("Celowy wyjątek testowy GlitchTip (/debug/boom/).")


@login_required
def home(request):
    """Dashboard z KPI cards — overdue inspections, active reservations, available machines.

    Wave 4 P0 (GDPR): ``@login_required`` chroni przed wyciekiem PII —
    wcześniej anonymous mógł zobaczyć listę 5 ostatnich rezerwacji z
    polem ``person`` (imię + nazwisko) na dashboardzie głównym.

    Wszystkie metryki maszyn / rezerwacji / budów liczone w 3 zapytaniach
    ``aggregate`` (zamiast 9 osobnych ``.count()``). To redukuje liczbę
    round-tripów do bazy z 9 → 3 dla widoku głównego (F5-3 / F7-B P2).

    Wave 14-F UX-1: dodane 3 querysets dla "morning checklist" — co operator
    sprawdza rano przy kawie: maszyny które dziś wyjeżdżają (start_date=dziś),
    maszyny które dziś wracają (end_date=dziś), maszyny aktualnie w trasie
    (active_today via manager). Każdy queryset jest limited[:5] z select_related
    żeby nie wybuchnąć N+1 (każda rezerwacja JOINuje machine + site).
    """
    from machines.models import Machine
    from reservations.models import ConstructionSite, Reservation

    today = date.today()
    horizon = today + timedelta(days=14)

    # Query 1 — wszystkie metryki maszyn w jednym round-tripie.
    # "Dostepne" = fizycznie w magazynie: W_MAGAZYNIE (wolne) + ZAREZERWOWANA
    # (sa w magazynie ale z przyszla rezerwacja). Operator chce wiedziec ile
    # maszyn fizycznie ma na stanie -- nie ile z nich nie ma JAKIEJKOLWIEK
    # rezerwacji. Subtitle w home.html rozbija na "X wolne + Y zarezerwowane".
    machine_stats = Machine.objects.aggregate(
        total=Count("id"),
        available=Count(
            "id",
            filter=Q(status__in=[Machine.Status.W_MAGAZYNIE, Machine.Status.ZAREZERWOWANA]),
        ),
        in_warehouse_free=Count("id", filter=Q(status=Machine.Status.W_MAGAZYNIE)),
        in_warehouse_booked=Count("id", filter=Q(status=Machine.Status.ZAREZERWOWANA)),
        on_site=Count("id", filter=Q(status=Machine.Status.NA_BUDOWIE)),
        in_service=Count("id", filter=Q(status=Machine.Status.W_SERWISIE)),
        inspections_overdue=Count("id", filter=Q(inspection_date__lt=today)),
        inspections_upcoming=Count(
            "id",
            filter=Q(inspection_date__gte=today, inspection_date__lte=horizon),
        ),
    )
    # Query 2 — metryki rezerwacji. F-6: dodajemy `overdue` (potwierdzona +
    # end_date przed dziś) — surfacing manager.overdue() w UI KPI cards.
    reservation_stats = Reservation.objects.aggregate(
        active=Count(
            "id",
            filter=Q(
                status=Reservation.Status.POTWIERDZONA,
                start_date__lte=today,
                end_date__gte=today,
            ),
        ),
        pending=Count("id", filter=Q(status=Reservation.Status.OCZEKUJACA)),
        overdue=Count(
            "id",
            filter=Q(status=Reservation.Status.POTWIERDZONA, end_date__lt=today),
        ),
    )
    # Query 3 — aktywne budowy.
    sites_active = ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA).count()

    context = {
        "kpi": {
            "machines_total": machine_stats["total"],
            "machines_available": machine_stats["available"],
            "machines_in_warehouse_free": machine_stats["in_warehouse_free"],
            "machines_in_warehouse_booked": machine_stats["in_warehouse_booked"],
            "machines_on_site": machine_stats["on_site"],
            "machines_in_service": machine_stats["in_service"],
            "inspections_overdue": machine_stats["inspections_overdue"],
            "inspections_upcoming": machine_stats["inspections_upcoming"],
            "reservations_active": reservation_stats["active"],
            "reservations_pending": reservation_stats["pending"],
            "reservations_overdue": reservation_stats["overdue"],
            "sites_active": sites_active,
        },
        # F-6: home.html linkuje do listy z filtrem end_before=today — daje
        # operatorowi konkretne wpisy do akcji "zadzwoń, gdzie maszyna jest".
        "today": today,
        # +1 zapytanie na recent_reservations (z select_related → tylko 1 JOIN).
        "recent_reservations": Reservation.objects.select_related("machine", "site").order_by(
            "-created_at"
        )[:5],
        # Wave 14-F UX-1 — morning checklist querysets. Każdy jest osobnym
        # zapytaniem (3 dodatkowe round-tripy), ale za to dostarczają
        # konkretne wpisy do akcji "co dziś jest do zrobienia" — wymaganie
        # Sebastian'a po walkthroughu 17 maja: liczby same w sobie (KPI)
        # nie wystarczą gdy operator chce zadzwonić do osoby która dziś
        # ma odbierać maszynę.
        "starting_today": (
            Reservation.objects.filter(
                status=Reservation.Status.POTWIERDZONA,
                start_date=today,
            )
            .select_related("machine", "site")
            .order_by("machine__uid")[:5]
        ),
        "ending_today": (
            Reservation.objects.filter(
                status=Reservation.Status.POTWIERDZONA,
                end_date=today,
            )
            .select_related("machine", "site")
            .order_by("machine__uid")[:5]
        ),
        "active_today": (
            Reservation.objects.active_today(today)
            .select_related("machine", "site")
            .order_by("end_date", "machine__uid")[:5]
        ),
    }
    return render(request, "home.html", context)


@login_required
@ratelimit(key="user", rate="30/m", method="GET", block=True)
def global_search_view(request):
    """Full-page wyniki lub HTMX partial dla typeahead dropdown.

    Wave 14-D: aktywuje dotąd-disabled input w topbar (base.html).

    Tryby:

    * **HTMX request** (``request.htmx is True``) — keyup z input topbara →
      renderuje ``core/_search_results.html`` jako fragment (mini-sekcje
      per kategoria, max 5 wpisów każdej).
    * **Full page** (Enter w input lub bezpośrednie wejście na /szukaj/) —
      renderuje ``core/search.html`` z header, formularzem + kompletną
      listą wyników po wszystkich kategoriach.

    Permission: ``@login_required`` — anonim widzi PII w polu ``person``
    rezerwacji, więc analogicznie do home view (Wave 4 P0).

    Wave 14-H Bundle M-2: rate limit 30/min per user — HTMX keyup
    dropdown na każdy znak strzela request'em, ale realny user nie
    przekroczy 30/min. Spam typeahead query pattern (np. bot script)
    blokowany przez 429 (handled przez chatbot.middleware.RatelimitedMiddleware).
    """
    query = request.GET.get("q", "").strip()
    results = global_search(query, user=request.user) if query else {}
    total = sum(len(items) for items in results.values())

    template = (
        "core/_search_results.html" if getattr(request, "htmx", False) else "core/search.html"
    )
    return render(
        request,
        template,
        {"query": query, "results": results, "total": total},
    )


# =============================================================================
# /mapy/ — Google Maps widget (BETA)
# =============================================================================
# Sebastian #60: mapa Polski z pin per maszyna w aktualnej lokalizacji
# (machine.location lub site.address z najnowszej aktywnej rezerwacji).
# Klik pin -> InfoWindow z miniaturka + UID + nazwa (link na detail) + status
# + przeglad + osoba odpowiedzialna. Frontend geocoding (MVP/BETA) -
# kazdy adres jest zapytany do Geocoding API przy render. Production-ready
# byloby cache lat/lng w Machine model + offline geocoding pipeline -
# TODO M3.

# Polska ASCII map - slugify nie zna polskiego "ł" (LATIN SMALL LETTER L WITH
# STROKE). Bez tej translacji `wozek widłowy` daje slug `wozek-widowy` ->
# fallback static image 404'uje. Te same wartosci co w
# machines/templatetags/machines_tags.py.
_POLISH_ASCII_MAP = str.maketrans({"ł": "l", "Ł": "L"})


def _machine_image_static_url(machine_type_value: str) -> str:
    """Zwraca static URL placeholder image per typ maszyny.

    Mirror logiki ``machine_image_url`` template taga - uzywamy slug-z-typu
    + fallback ``inne.webp`` zamiast machine.image (kazda maszyna ma fallback
    obraz, nawet bez uploaded zdjecia). Brak fallback do uploaded image bo
    z view rendering pip JSON, nie HTML - dla MVP wystarcza static.
    """
    slug = slugify((machine_type_value or "").translate(_POLISH_ASCII_MAP))
    if not slug:
        slug = "inne"
    return static(f"images/machines/{slug}.webp")


# Default warehouse address - fallback gdy maszyna nie ma machine.location
# i nie jest na budowie. Sebastian 2026-05-31 wieczor: zmiana na Wroclaw bo
# wiekszosc maszyn dotad spadala na jeden punkt w Warszawie i sie nakladala.
# Frontend dodaje spiral jitter zeby kilka maszyn z tym samym adresem nie
# pojawialo sie dokladnie w tym samym miejscu (kazda offsetowana o ~30m).
_DEFAULT_WAREHOUSE_ADDRESS = "ul. Krakowska 100, 50-424 Wroclaw"


@login_required
def maps_view(request):
    """Widok /mapy/ - Google Maps z pinami maszyn (BETA).

    Renderuje:
    - mape Polski (centered lat=52, lng=19, zoom=6)
    - pin per kazda maszyna ``is_reservable=True`` (excluding WYCOFANA)
    - klik pin = InfoWindow z miniaturka + szczegoly + link do detail

    Logika lokalizacji pinu (Sebastian update 2026-05-31 wieczor):

    * Jesli ``machine.status == "Na budowie"`` -> bierzemy NAJNOWSZA
      ``confirmed`` rezerwacje **covering today** (``start_date <= today
      <= end_date``). Priorytet adresu w obrebie tej rezerwacji:
      ``reservation.address`` > ``reservation.site.address`` >
      ``machine.location`` > ``DEFAULT_WAREHOUSE_ADDRESS``.
      Pin "podaza" za maszyna na budowie.
    * Wpp (W magazynie / Zarezerwowana / W serwisie) -> uzywamy
      ``machine.location`` (lub default warehouse jesli puste).

    Geocoding robi sie na frontendzie (Google Geocoding API) - kazdy adres
    konwertowany do lat/lng przy page load. MVP/BETA, M3 TODO: cache lat/lng
    w Machine model + offline pipeline (rate limits dla setek maszyn).

    Kontekst dla template:
    - ``pins_json``: JSON string z lista dict-ow (uid, name, photo, ...).
    - ``gmap_api_key``: GOOGLE_MAPS_API_KEY z settings (puste -> warning panel).
    - ``pins_count``: int, ile pinow na mapie (do nagłówka).
    """
    # Lokalne importy: machines/reservations sa heavyweight (django_filters,
    # tons of dependencies). Lazy import zachowuje top of file lekki + unika
    # potencjalnych circular deps gdyby core stalo sie zaleznoscia.
    from machines.models import Machine
    from reservations.models import Reservation

    today = date.today()

    # Wykluczamy WYCOFANA - tak samo jak timeline view. WYCOFANA nie maja juz
    # rezerwacji ani sensownej lokalizacji - na mapie byly by martwymi pinami.
    machines_qs = Machine.objects.exclude(status=Machine.Status.WYCOFANA).filter(is_reservable=True)

    # Prefetch confirmed rezerwacji covering today (do "podazania pinu" za
    # maszyna na budowie) + osobno najnowsza confirmed res (do osoby
    # odpowiedzialnej dla maszyn poza statusem Na budowie - np. zarezerwowanych).
    # Sort desc - [0] dostaje najnowsza spelniajaca warunek.
    from django.db.models import Prefetch

    current_reservations = (
        Reservation.objects.filter(
            status=Reservation.Status.POTWIERDZONA,
            start_date__lte=today,
            end_date__gte=today,
        )
        .select_related("site")
        .order_by("-start_date")
    )
    # Fallback prefetch - dowolna confirmed rezerwacja (nawet przyszla)
    # zeby maszyna ZAREZERWOWANA tez miala osobe odpowiedzialna w popup.
    any_confirmed = (
        Reservation.objects.filter(status=Reservation.Status.POTWIERDZONA)
        .select_related("site")
        .order_by("-start_date")
    )
    machines_qs = machines_qs.prefetch_related(
        Prefetch("reservations", queryset=current_reservations, to_attr="current_today"),
        Prefetch("reservations", queryset=any_confirmed, to_attr="any_confirmed"),
    )

    pins: list[dict] = []
    for machine in machines_qs:
        # current = covering today; fallback = jakakolwiek confirmed.
        current = machine.current_today[0] if machine.current_today else None
        fallback = machine.any_confirmed[0] if machine.any_confirmed else None
        # Dla osoby + site w popup uzywamy current jesli jest, wpp fallback.
        display_res = current or fallback

        # Wybor adresu - Sebastian's priorytet (update 2026-05-31 wieczor):
        # Na budowie -> covering-today: res.address > site.address > machine.location
        # Inne -> machine.location -> default.
        # Fix 2026-05-31 wieczor: machine.location moze byc "Magazyn" (string,
        # nie adres) — to powoduje Geocoding ZERO_RESULTS. Traktujemy wszystkie
        # warianty 'Magazyn'/pustki jako brak adresu i uzywamy default warehouse.
        def _real_address(addr):
            stripped = (addr or "").strip()
            # Rozszerzona lista non-adres slow (Sebastian audit 2026-05-31 wieczor):
            # bylo 25 maszyn "Magazyn", 2 "Serwis", 2 "Magazyn glowny" -> wszystkie
            # spadaly na default warehouse. Teraz idą tam jawnie + frontend jitter
            # rozsuwa je w mini-spirali zeby nie nakladaly sie na jednym pinie.
            non_addresses = (
                "magazyn",
                "warehouse",
                "magazynow",
                "magazyn glowny",
                "magazyn główny",
                "serwis",
                "service",
                "warsztat",
            )
            if not stripped or stripped.lower() in non_addresses:
                return None
            return stripped

        if machine.status == Machine.Status.NA_BUDOWIE and current is not None:
            location_address = (
                _real_address(current.address)
                or (_real_address(current.site.address) if current.site_id else None)
                or _real_address(machine.location)
                or _DEFAULT_WAREHOUSE_ADDRESS
            )
        else:
            location_address = _real_address(machine.location) or _DEFAULT_WAREHOUSE_ADDRESS

        site_label = (
            f"{display_res.site.project_number} - {display_res.site.name}"
            if display_res and display_res.site_id
            else ""
        )

        # Image: priorytet ImageField na machine, fallback static per typ.
        try:
            photo_url = (
                machine.image.url
                if machine.image
                else _machine_image_static_url(machine.machine_type)
            )
        except ValueError:
            photo_url = _machine_image_static_url(machine.machine_type)

        pins.append(
            {
                "uid": machine.uid,
                "name": machine.name,
                "machine_type": machine.get_machine_type_display(),
                "status": machine.get_status_display(),
                "inspection_date": (
                    machine.inspection_date.strftime("%d.%m.%Y")
                    if machine.inspection_date
                    else _("brak danych")
                ),
                "inspection_status": machine.inspection_status,
                "location_address": location_address,
                "site_label": site_label,
                "responsible": display_res.responsible_person if display_res else "",
                "person": display_res.person if display_res else "",
                "detail_url": reverse("machines:detail", kwargs={"uid": machine.uid}),
                "photo_url": photo_url,
            }
        )

    context = {
        # Przekazujemy listę — szablon renderuje ją przez ``json_script``, które
        # escapuje ``< > &`` (ochrona przed stored-XSS, gdy pole tekstowe maszyny/
        # budowy/adresu zawiera np. ``</script>``). NIE używać ``|safe`` na danych.
        "pins": pins,
        "pins_count": len(pins),
        "gmap_api_key": settings.GOOGLE_MAPS_API_KEY,
    }
    return render(request, "core/maps.html", context)
