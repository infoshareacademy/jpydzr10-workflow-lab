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

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django_ratelimit.decorators import ratelimit

from core.search import global_search


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
    machine_stats = Machine.objects.aggregate(
        total=Count("id"),
        available=Count("id", filter=Q(status=Machine.Status.W_MAGAZYNIE)),
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
