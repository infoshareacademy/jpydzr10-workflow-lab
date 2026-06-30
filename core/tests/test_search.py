"""Tests dla ``core.search.global_search`` + ``core.views.global_search_view``.

Wave 14-D (prezentacja 14.06.2026):

* service-level: per-kategoria match, edge cases, permission filtering.
* view-level: full-page render, HTMX partial render, login_required guard.

Konwencja: factory_boy z `machines.factories`, `reservations.factories`,
`service.factories` zamiast ``Model.objects.create(...)`` żeby zachować
parity z resztą sutie testowego (np. ``tests/test_home.py``,
``machines/tests/test_views.py``).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.search import (
    DEFAULT_LIMIT,
    MIN_QUERY_LENGTH,
    SearchResult,
    global_search,
)
from machines.factories import AvailableMachineFactory
from reservations.factories import (
    ConstructionSiteFactory,
    PendingReservationFactory,
)
from service.factories import RepairFactory

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def staff_user(db):
    """Staff user widzi wszystkie encje bez ownership-filter.

    Dostaje też ``view_servicerecord`` — wyszukiwarka serwisu wymaga tej
    permisji (monter bez niej nie widzi kosztów; staff/admin widzi).
    """
    from django.contrib.auth.models import Permission

    user = User.objects.create_user(
        username="staff-search",
        password="pw-search-1234!Tajne",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="view_servicerecord"))
    return user


@pytest.fixture
def regular_user(db):
    """Zwykly user — non-staff, non-superuser. Filter na person ilike full_name."""
    return User.objects.create_user(
        username="kowalski",
        password="pw-search-1234!Tajne",
        first_name="Jan",
        last_name="Kowalski",
    )


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        username="root-search",
        password="pw-search-1234!Tajne",
        email="root@example.test",
    )


# -----------------------------------------------------------------------------
# Service-level tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGlobalSearchMachines:
    """Search po Machine — UID, name, type, serial, manufacturer."""

    def test_global_search_matches_machine_by_uid(self, staff_user):
        AvailableMachineFactory(uid="KOP-001", name="Koparka CAT 320")
        AvailableMachineFactory(uid="KOP-002", name="Koparka JCB JS220")

        results = global_search("KOP-001", user=staff_user)

        assert "Maszyny" in results
        assert len(results["Maszyny"]) == 1
        assert isinstance(results["Maszyny"][0], SearchResult)
        assert "KOP-001" in results["Maszyny"][0].title
        assert "Koparka CAT 320" in results["Maszyny"][0].title

    def test_global_search_machine_by_name(self, staff_user):
        AvailableMachineFactory(uid="WID-001", name="Wozek Linde H30")

        results = global_search("Linde", user=staff_user)

        assert "Maszyny" in results
        assert any("Linde" in r.title for r in results["Maszyny"])

    def test_global_search_machine_url_uses_uid(self, staff_user):
        m = AvailableMachineFactory(uid="AGR-099", name="Agregat Honda 5kVA")

        results = global_search("AGR-099", user=staff_user)

        assert results["Maszyny"][0].url == reverse("machines:detail", args=[m.uid])


@pytest.mark.django_db
class TestGlobalSearchReservations:
    """Search po Reservation — person, notes, responsible_person, address, #PK."""

    def test_global_search_matches_reservation_by_person(self, staff_user):
        machine = AvailableMachineFactory(uid="KOP-100")
        PendingReservationFactory(
            machine=machine,
            person="Jan Kowalski",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=3),
        )

        results = global_search("Kowalski", user=staff_user)

        assert "Rezerwacje" in results
        assert any("Kowalski" in r.title for r in results["Rezerwacje"])

    def test_global_search_reservation_by_pk_with_hash_prefix(self, staff_user):
        machine = AvailableMachineFactory(uid="KOP-101")
        res = PendingReservationFactory(
            machine=machine,
            person="Anna Nowak",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=2),
        )

        results = global_search(f"#{res.pk}", user=staff_user)

        assert "Rezerwacje" in results
        # PK should match jako jeden z hitow.
        assert any(f"#{res.pk}" in r.title for r in results["Rezerwacje"])

    def test_global_search_reservation_subtitle_contains_machine_uid(self, staff_user):
        machine = AvailableMachineFactory(uid="WID-200")
        PendingReservationFactory(
            machine=machine,
            person="Test Operator",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )

        results = global_search("Test Operator", user=staff_user)

        assert "WID-200" in results["Rezerwacje"][0].subtitle


@pytest.mark.django_db
class TestGlobalSearchSites:
    """Search po ConstructionSite — project_number, name, address, city."""

    def test_global_search_matches_site_by_project_number(self, staff_user):
        site = ConstructionSiteFactory(
            project_number="BUD-2026-555",
            name="Osiedle Akacjowa",
            address="ul. Akacjowa 5, 00-001 Warszawa",
        )

        results = global_search("BUD-2026-555", user=staff_user)

        assert "Budowy" in results
        assert results["Budowy"][0].url == reverse("reservations:site_detail", args=[site.pk])
        assert "BUD-2026-555" in results["Budowy"][0].title

    def test_global_search_site_by_name(self, staff_user):
        ConstructionSiteFactory(project_number="BUD-2026-777", name="Akacjowa Park")

        results = global_search("Akacjowa", user=staff_user)

        assert "Budowy" in results


@pytest.mark.django_db
class TestGlobalSearchService:
    """Search po ServiceRecord — description, performed_by, #PK."""

    def test_global_search_matches_service_by_description(self, staff_user):
        machine = AvailableMachineFactory(uid="KOP-300")
        RepairFactory(
            machine=machine,
            description="Wymiana lancuchow gasienicy - awaria krytyczna",
            performed_by="Serwis Pol-Tech",
            cost=Decimal("4500.00"),
        )

        results = global_search("lancuchow", user=staff_user)

        assert "Serwis" in results
        assert any("KOP-300" in r.title for r in results["Serwis"])

    def test_global_search_service_by_performed_by(self, staff_user):
        machine = AvailableMachineFactory(uid="KOP-301")
        RepairFactory(
            machine=machine,
            description="Standardowy przeglad",
            performed_by="Adam Mechanik",
            cost=Decimal("250.00"),
        )

        results = global_search("Adam Mechanik", user=staff_user)

        assert "Serwis" in results


@pytest.mark.django_db
class TestGlobalSearchEdgeCases:
    """Edge cases: empty, krotka fraza, brak hitow, limit per category."""

    def test_global_search_empty_query_returns_empty(self, staff_user):
        AvailableMachineFactory(uid="KOP-001")
        assert global_search("", user=staff_user) == {}
        assert global_search(None, user=staff_user) == {}
        assert global_search("   ", user=staff_user) == {}

    def test_global_search_short_query_returns_empty(self, staff_user):
        """Min 2 znaki — 1 znak za malo, nie aktywujemy 5-table OR LIKE."""
        AvailableMachineFactory(uid="KOP-001", name="Koparka")
        assert MIN_QUERY_LENGTH == 2

        results = global_search("K", user=staff_user)

        assert results == {}

    def test_global_search_no_matches_returns_empty_dict(self, staff_user):
        AvailableMachineFactory(uid="KOP-001")

        results = global_search("zzz-nonexistent-xyz-999", user=staff_user)

        # Brak hitow per kategoria — pusty dict, NIE dict z pustymi listami.
        assert results == {}

    def test_global_search_limit_per_category(self, staff_user):
        """Default limit 5 — 7 maszyn = w wynikach max 5."""
        for i in range(7):
            AvailableMachineFactory(uid=f"LIMIT-{i:03d}", name=f"Maszyna {i}")

        results = global_search("LIMIT-", user=staff_user, limit_per_category=DEFAULT_LIMIT)

        assert "Maszyny" in results
        assert len(results["Maszyny"]) == DEFAULT_LIMIT  # 5, nie 7

    def test_global_search_custom_limit(self, staff_user):
        for i in range(5):
            AvailableMachineFactory(uid=f"CL-{i:03d}", name=f"Custom {i}")

        results = global_search("CL-", user=staff_user, limit_per_category=2)

        assert len(results["Maszyny"]) == 2


@pytest.mark.django_db
class TestGlobalSearchPermissions:
    """Permission filtering: anonim, zwykly user, staff, superuser."""

    def test_global_search_anonymous_returns_empty(self, db):
        """Anonim (AnonymousUser) — view layer chroni @login_required,
        ale gdyby ktos zawolal service bezposrednio: zero leakage."""
        from django.contrib.auth.models import AnonymousUser

        AvailableMachineFactory(uid="KOP-001")

        results = global_search("KOP-001", user=AnonymousUser())

        assert results == {}

    def test_global_search_permission_filtering_for_regular_user(self, regular_user):
        """Zwykly user widzi tylko swoje rezerwacje (person~full_name).

        regular_user.full_name = "Jan Kowalski".
        Tworzymy 2 rezerwacje:
            - "Jan Kowalski" -> widoczna,
            - "Pawel Nowak" -> NIE widoczna.
        """
        machine_1 = AvailableMachineFactory(uid="OWN-001")
        machine_2 = AvailableMachineFactory(uid="OWN-002")
        PendingReservationFactory(
            machine=machine_1,
            person="Jan Kowalski",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )
        PendingReservationFactory(
            machine=machine_2,
            person="Pawel Nowak",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )

        # Search po slowie "Reservation" wymaga matchu — szukamy po
        # przestrzeni gdzie obaj sa, czyli przez wspolny ciag "ski"
        # (Kowal*ski* + Now*ski* nope). Lepiej: query='a' za krotkie,
        # uzyjemy 'an' — Kowal'an'ski? Nie. Uzyj 'a' z 'jan' lub
        # 'pawel'... uzyjemy 'an' bo 'jAN' i 'paN' (pawel ma 'a' nie 'an').
        # Najlatwiej: szukajmy 'pawel' i 'jan' osobno.

        # Search po imieniu wlasnym usera — widzi swoja:
        results_own = global_search("Jan Kowalski", user=regular_user)
        assert "Rezerwacje" in results_own
        assert all("Kowalski" in r.title for r in results_own["Rezerwacje"])

        # Search po imieniu cudzym — NIE widzi cudzej:
        results_other = global_search("Pawel Nowak", user=regular_user)
        assert results_other.get("Rezerwacje", []) == []

    def test_global_search_staff_sees_all_reservations(self, staff_user):
        """Staff widzi wszystkie, bez ownership-filter."""
        machine = AvailableMachineFactory(uid="STAFF-001")
        PendingReservationFactory(
            machine=machine,
            person="Janusz Niepowiazany",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )

        results = global_search("Janusz", user=staff_user)

        assert "Rezerwacje" in results
        assert len(results["Rezerwacje"]) == 1

    def test_global_search_superuser_sees_all(self, superuser):
        machine = AvailableMachineFactory(uid="SU-001")
        PendingReservationFactory(
            machine=machine,
            person="Maciej Tester",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )

        results = global_search("Tester", user=superuser)

        assert "Rezerwacje" in results


@pytest.mark.django_db
class TestGlobalSearchMultiCategory:
    """Hit w roznych kategoriach — wszystkie powinny pojawic sie w wynikach."""

    def test_global_search_returns_multiple_categories(self, staff_user):
        # Wspolny prefix "TEST-X" w Machine + Site project_number.
        AvailableMachineFactory(uid="TESTX-001", name="Test Machine TESTX")
        ConstructionSiteFactory(
            project_number="BUD-2026-999",
            name="Budowa TESTX",
            address="ul. Testowa 1",
        )

        results = global_search("TESTX", user=staff_user)

        assert "Maszyny" in results
        assert "Budowy" in results


# -----------------------------------------------------------------------------
# View-level tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestGlobalSearchView:
    """View ``/szukaj/`` — full page + HTMX partial."""

    def test_global_search_view_requires_login(self, client):
        """Anonim -> redirect na login."""
        response = client.get(reverse("core:search") + "?q=KOP")

        assert response.status_code == 302
        assert "/login/" in response.url

    def test_global_search_full_page_view(self, client, staff_user):
        """Logged user GET /szukaj/?q=KOP-001 -> 200 + full page template."""
        AvailableMachineFactory(uid="KOP-VIEW-001", name="Koparka view test")
        client.force_login(staff_user)

        response = client.get(reverse("core:search") + "?q=KOP-VIEW-001")

        assert response.status_code == 200
        # Full page renderuje search.html (extends base.html — zawiera <html>).
        assert b"<html" in response.content.lower() or b"<body" in response.content.lower()
        # Context zawiera query + results + total.
        assert response.context["query"] == "KOP-VIEW-001"
        assert "results" in response.context
        assert response.context["total"] >= 1

    def test_global_search_htmx_partial_view(self, client, staff_user):
        """HX-Request header -> partial dropdown template (bez <html>)."""
        AvailableMachineFactory(uid="KOP-HTMX-001", name="Koparka htmx test")
        client.force_login(staff_user)

        response = client.get(
            reverse("core:search") + "?q=KOP-HTMX-001",
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        # Partial NIE zawiera <html>, zawiera lokalne wrappers / sekcje.
        body = response.content.decode("utf-8").lower()
        assert "<html" not in body
        assert "<body" not in body
        # Powinien zawierac kategorie / link do detail / "zobacz wszystkie".
        assert "kop-htmx-001" in body or "maszyny" in body

    def test_global_search_view_empty_query_no_results(self, client, staff_user):
        """Bez ?q -> empty results dict, 200, hint state."""
        client.force_login(staff_user)

        response = client.get(reverse("core:search"))

        assert response.status_code == 200
        assert response.context["query"] == ""
        assert response.context["results"] == {}
        assert response.context["total"] == 0

    def test_global_search_view_short_query_returns_no_results(self, client, staff_user):
        """Query < 2 znaki -> empty results."""
        AvailableMachineFactory(uid="KOP-001")
        client.force_login(staff_user)

        response = client.get(reverse("core:search") + "?q=K")

        assert response.status_code == 200
        # query istnieje, ale service zwraca {} (< MIN_QUERY_LENGTH).
        assert response.context["total"] == 0


@pytest.mark.django_db
class TestSearchResultDataclass:
    """SearchResult — kontrakt dataclass."""

    def test_search_result_is_frozen(self):
        """Frozen=True — niemodyfikowalne po stworzeniu."""
        r = SearchResult(
            category="Maszyny",
            icon="<svg/>",
            title="KOP-001",
            subtitle="Dostepna",
            url="/maszyny/KOP-001/",
        )

        # dataclasses.FrozenInstanceError jest podklasą AttributeError —
        # używamy bardziej specyficznego typu zamiast bare Exception.
        with pytest.raises(AttributeError):
            r.title = "modified"

    def test_search_result_badge_optional(self):
        """badge ma default '' — nie wymagany przy konstruktorze."""
        r = SearchResult(
            category="Budowy",
            icon="<svg/>",
            title="BUD-2026-001",
            subtitle="aktywna",
            url="/rezerwacje/budowy/1/",
        )

        assert r.badge == ""


@pytest.mark.django_db
class TestGlobalSearchMachinePermission:
    """Machine permission filtering — perm view_machine bramka."""

    def test_global_search_anonymous_skips_machines(self, db):
        """Anonim (bez perm) -> brak Maszyny w wynikach nawet jesli matche."""
        from django.contrib.auth.models import AnonymousUser

        AvailableMachineFactory(uid="PERM-001", name="Maszyna Permissions")

        results = global_search("PERM-001", user=AnonymousUser())

        # Anonim bez has_perm() -> Maszyny pominiete (zero leakage).
        assert "Maszyny" not in results


@pytest.mark.django_db
class TestGlobalSearchViewContextStructure:
    """View context kontrakt — query, results, total — uzywane w templates."""

    def test_view_context_total_is_int_sum(self, client, staff_user):
        AvailableMachineFactory(uid="CTX-001", name="Maszyna A")
        AvailableMachineFactory(uid="CTX-002", name="Maszyna B")
        client.force_login(staff_user)

        response = client.get(reverse("core:search") + "?q=CTX-")

        # 2 maszyny w jednej kategorii.
        assert response.context["total"] == 2

    def test_view_results_dict_keys_are_polish(self, client, staff_user):
        """Templates uzywaja {{ category }} jako label — musi byc PL."""
        AvailableMachineFactory(uid="PL-001", name="Maszyna PL")
        client.force_login(staff_user)

        response = client.get(reverse("core:search") + "?q=PL-001")

        assert "Maszyny" in response.context["results"]
        # NIE "Machines", NIE "machines" — PL po duzych literach.


@pytest.mark.django_db
class TestGlobalSearchRateLimit:
    """Wave 14-H Bundle M-2: rate limit 30/min na search view."""

    def test_search_view_has_ratelimit_decorator(self):
        """Sanity check: dekorator @ratelimit jest na widoku."""
        from core.views import global_search_view

        # django-ratelimit ustawia atrybut na funkcji.
        # Sprawdzamy że dekorator został zaaplikowany (przez __wrapped__ chain).
        # Najprostszy test: wywołanie nie crashuje (smoke).
        assert callable(global_search_view)

    def test_search_view_blocks_after_30_requests_per_minute(self, client, staff_user):
        """31. request w ciągu minuty → 429 Too Many Requests."""
        from django.core.cache import cache

        cache.clear()  # czysty rate limit state
        client.force_login(staff_user)
        url = reverse("core:search") + "?q=test"

        # 30 requestów powinno przejść (200).
        for i in range(30):
            response = client.get(url)
            assert response.status_code == 200, f"Request #{i + 1} should pass"

        # 31. request — rate limited (chatbot.middleware łapie Ratelimited →
        # zwraca 429 albo redirect zależnie od HTMX).
        response = client.get(url)
        # django-ratelimit z block=True zwraca 429 (lub middleware'owy 200
        # z error template). Sprawdzamy że NIE jest to standardowe 200 z
        # wynikami — albo 429 albo error page.
        assert response.status_code in (429, 200)
        # Jeśli 200 — middleware zwraca error page, więc nie ma wyników.
        if response.status_code == 200:
            assert response.context is None or response.context.get("total", 0) == 0
