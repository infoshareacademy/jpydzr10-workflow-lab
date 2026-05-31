"""Wave 12 — testy widoków pokrywające ścieżki niedotykane przez `test_views.py`.

Skupia się na widokach Wave 9-11 (B-4, B-6, B-7) i ich error-pathach
(swap_machine, change_operator, report_breakdown), oraz update view
(form_valid z ValidationError z service warstwy, superuser bypass ownership,
empty-name queryset).

Każdy test sprawdza pojedynczy invariant — error → flash + redirect bez
mutacji stanu; happy path → 302 do detail/batch.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from freezegun import freeze_time

from machines.models import Machine
from reservations.factories import (
    ConfirmedReservationFactory,
    PendingReservationFactory,
)
from reservations.models import Reservation

# =============================================================================
# update_reservation view — service-level ValidationError
# =============================================================================


@pytest.mark.django_db
class TestReservationUpdateValidationError:
    """form_valid → service rzuca ValidationError → form_invalid z błędem."""

    @freeze_time("2026-05-16")
    def test_update_with_service_validation_error_renders_form(
        self, client_logged, machine, monkeypatch
    ):
        """Service rzuca VR → form_invalid path (lines 296-298)."""

        from django.core.exceptions import ValidationError

        def boom(*args, **kwargs):
            raise ValidationError("Service-level VR forced for coverage test.")

        # Monkey-patch service'u używanego przez view (zaimportowany do views).
        from reservations import views as views_mod

        monkeypatch.setattr(views_mod, "update_reservation", boom)

        res = PendingReservationFactory(
            machine=machine,
            person="tester",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        response = client_logged.post(
            reverse("reservations:update", args=[res.pk]),
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": "2030-02-01",
                "end_date": "2030-02-05",
                "person": "tester",
                # Wave 14-A Bundle 4 -- address + responsible_person wymagane.
                "address": "Polna 5",
                "responsible_person": "Jan Kowalski",
                "notes": "",
            },
        )
        # form_invalid → 200 z błędem
        assert response.status_code == 200

    @freeze_time("2026-05-16")
    def test_update_success_path_redirects_to_detail(self, client_logged, machine):
        """Happy path: form valid + service ok → 302 do detail."""
        res = PendingReservationFactory(
            machine=machine,
            person="tester",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        response = client_logged.post(
            reverse("reservations:update", args=[res.pk]),
            data={
                "machine": machine.pk,
                "site": "",
                "start_date": "2030-01-10",  # nowy zakres bez konfliku
                "end_date": "2030-01-15",
                "person": "tester",
                # Wave 14-A Bundle 4 -- address + responsible_person wymagane.
                "address": "Polna 5, Krakow",
                "responsible_person": "Jan Kowalski",
                "notes": "Updated",
            },
        )
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.start_date == date(2030, 1, 10)


@pytest.mark.django_db
class TestReservationUpdateSuperuserBypass:
    """Superuser widzi WSZYSTKIE rezerwacje (bypass ownership filter)."""

    @pytest.fixture
    def superuser_client(self, client, db):
        user_model = get_user_model()
        admin = user_model.objects.create_superuser(
            username="admin",
            email="a@a.test",
            password="secret-pw-123!",
        )
        client.force_login(admin)
        return client

    def test_superuser_sees_someone_elses_reservation(self, superuser_client, machine):
        """Reservation z innym person → superuser dostaje 200 (a nie 404)."""
        res = PendingReservationFactory(
            machine=machine,
            person="Ktoś Inny Cudzy",
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = superuser_client.get(reverse("reservations:update", args=[res.pk]))
        assert response.status_code == 200


@pytest.mark.django_db
class TestReservationUpdateEmptyName:
    """User z całkowicie pustym imieniem i pustym username → queryset.none()."""

    def test_user_with_empty_normalized_name_sees_nothing(self, client, db, machine):
        """B-5 edge: normalize zwraca '' → get_queryset zwraca .none().

        Tworzymy username z samych znaków cyrylickich — po NFKD + ASCII drop
        zostaje pusty string. Defense-in-depth check (gdyby ktoś w przyszłości
        podpiął email-as-username z samych non-ASCII znaków).
        """
        user_model = get_user_model()
        # 'абв' to cyrylica — NFKD nie rozkłada, encode('ASCII','ignore') zwraca b''
        # Django UnicodeUsernameValidator dopuszcza non-ASCII letters.
        user = user_model.objects.create_user(
            username="абв",  # NFKD+ASCII drop = ''
            password="secret-pw-123!",
            first_name="",
            last_name="",
        )
        perms = Permission.objects.filter(
            content_type__app_label="reservations",
            codename="change_reservation",
        )
        user.user_permissions.add(*perms)
        client.force_login(user)

        # Stwórz res z dowolnym person — filter zwróci pusty queryset.
        res = PendingReservationFactory(
            machine=machine,
            person="cokolwiek",
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=10),
        )
        response = client.get(reverse("reservations:update", args=[res.pk]))
        assert response.status_code == 404  # .none() → 404 z DetailView lookup


# =============================================================================
# reservation_complete — z actual_return_date
# =============================================================================


@pytest.mark.django_db
class TestCompleteWithActualReturnDate:
    """B-3: opcjonalny `actual_return_date` w POST zwraca maszynę wcześniej."""

    def test_complete_with_actual_return_date_sets_field(self, client, user, machine):
        with freeze_time("2030-01-07"):
            client.force_login(user)
            res = ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 10),
            )
            response = client.post(
                reverse("reservations:complete", args=[res.pk]),
                data={"actual_return_date": "2030-01-07"},
            )
            assert response.status_code == 302
            res.refresh_from_db()
            assert res.status == Reservation.Status.ZAKONCZONA
            assert res.actual_return_date == date(2030, 1, 7)

    def test_complete_already_completed_flashes_error(self, client_logged, machine):
        """Re-complete (status=ZAKONCZONA) → ValidationError → flash."""
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        # Pre-complete it
        client_logged.post(reverse("reservations:complete", args=[res.pk]))
        # Drugi complete — service powinien rzucić
        response = client_logged.post(reverse("reservations:complete", args=[res.pk]))
        assert response.status_code == 302  # redirect z flash error


# =============================================================================
# reservation_change_operator — B-4
# =============================================================================


@pytest.mark.django_db
class TestChangeOperatorView:
    """B-4: POST /<pk>/zmien-osobe/."""

    def test_change_operator_success(self, client_logged, machine):
        res = ConfirmedReservationFactory(
            machine=machine,
            person="Stary Operator",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "Nowy Operator"},
        )
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.person == "Nowy Operator"

    def test_change_operator_short_name_invalid_form(self, client_logged, machine):
        """new_person < min_length (3) → flash error + redirect, bez zmian."""
        res = ConfirmedReservationFactory(
            machine=machine,
            person="Stary Operator",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "XY"},
        )
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.person == "Stary Operator"  # bez zmian

    def test_change_operator_closed_reservation_flashes_error(self, client_logged, machine):
        """is_closed=True → service rzuca ValidationError → flash."""
        res = ConfirmedReservationFactory(
            machine=machine,
            person="Operator",
            status=Reservation.Status.ZAKONCZONA,  # already closed
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        response = client_logged.post(
            reverse("reservations:change_operator", args=[res.pk]),
            data={"new_person": "Nowy Operator"},
        )
        assert response.status_code == 302
        res.refresh_from_db()
        assert res.person == "Operator"  # service blokuje, bez zmian


# =============================================================================
# reservation_swap_machine — B-6
# =============================================================================


@pytest.mark.django_db
class TestSwapMachineView:
    """B-6: POST /<pk>/wymien-maszyne/."""

    def test_swap_machine_success(self, client, user, machine, second_machine):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            res = ConfirmedReservationFactory(
                machine=machine,
                person="Operator",
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 15),
            )
            response = client.post(
                reverse("reservations:swap_machine", args=[res.pk]),
                data={"new_machine": second_machine.pk, "reason": "Awaria hydrauliki"},
            )
            # Sukces → redirect do detail nowej rezerwacji
            assert response.status_code == 302
            # Oryginalna rezerwacja → ZAKONCZONA
            res.refresh_from_db()
            assert res.status == Reservation.Status.ZAKONCZONA
            # Nowa rezerwacja na second_machine istnieje
            assert Reservation.objects.filter(machine=second_machine).exists()

    def test_swap_machine_invalid_form_no_machine(self, client, user, machine):
        """Brak new_machine → form invalid → flash + redirect bez side-effectów."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            res = ConfirmedReservationFactory(
                machine=machine,
                person="Operator",
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 15),
            )
            before = Reservation.objects.count()
            response = client.post(
                reverse("reservations:swap_machine", args=[res.pk]),
                data={"new_machine": "", "reason": ""},
            )
            assert response.status_code == 302
            # Nic się nie zmieniło
            assert Reservation.objects.count() == before
            res.refresh_from_db()
            assert res.status == Reservation.Status.POTWIERDZONA

    def test_swap_machine_with_conflict_flashes_error(self, client, user, machine, second_machine):
        """second_machine ma zachodzącą rezerwację → ValidationError → flash."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            # Confirmed na second_machine w tym samym okresie
            ConfirmedReservationFactory(
                machine=second_machine,
                start_date=date(2030, 1, 5),
                end_date=date(2030, 1, 20),
            )
            res = ConfirmedReservationFactory(
                machine=machine,
                person="Operator",
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 15),
            )
            response = client.post(
                reverse("reservations:swap_machine", args=[res.pk]),
                data={"new_machine": second_machine.pk, "reason": "Awaria"},
            )
            # Service rzuca ValidationError → flash + redirect (NIE do nowej)
            assert response.status_code == 302
            # Oryginalna rezerwacja niezmieniona
            res.refresh_from_db()
            assert res.status == Reservation.Status.POTWIERDZONA


# =============================================================================
# reservation_report_breakdown
# =============================================================================


@pytest.mark.django_db
class TestReportBreakdownView:
    """B-X: POST /<pk>/awaria/ — one-click zgłoś awarię."""

    def test_report_breakdown_success(self, client, user, machine):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            res = ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 15),
            )
            response = client.post(
                reverse("reservations:report_breakdown", args=[res.pk]),
                data={"description": "Pęknięty wąż hydrauliczny"},
            )
            assert response.status_code == 302
            res.refresh_from_db()
            assert res.status == Reservation.Status.ZAKONCZONA
            machine.refresh_from_db()
            assert machine.status == Machine.Status.W_SERWISIE

    def test_report_breakdown_empty_description_flashes_error(self, client_logged, machine):
        """Brak description → ValidationError z service → flash + redirect."""
        res = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 15),
        )
        response = client_logged.post(
            reverse("reservations:report_breakdown", args=[res.pk]),
            data={"description": ""},
        )
        assert response.status_code == 302
        # Rezerwacja niezmieniona
        res.refresh_from_db()
        assert res.status == Reservation.Status.POTWIERDZONA


# =============================================================================
# CheckConflictView — exclude_pk parsing
# =============================================================================


@pytest.mark.django_db
class TestCheckConflictExcludePk:
    """CheckConflictView: exclude_pk parsing + ValidationError swallow."""

    def test_exclude_pk_int_excludes_reservation(self, client_logged, machine):
        """exclude_pk=<own_pk> → nie widzi własnej rezerwacji jako konflikt."""
        existing = ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {
                "machine": machine.pk,
                "start_date": "2030-01-05",
                "end_date": "2030-01-08",
                "exclude_pk": existing.pk,
            },
        )
        # Brak konfliku (excluded), 204
        assert response.status_code == 204

    def test_exclude_pk_invalid_falls_back_to_none(self, client_logged, machine):
        """exclude_pk='abc' → ValueError → exclude_pk=None → konflikt detected."""
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {
                "machine": machine.pk,
                "start_date": "2030-01-05",
                "end_date": "2030-01-08",
                "exclude_pk": "not-a-number",
            },
        )
        # Konflikt widoczny
        assert response.status_code == 200

    def test_check_conflict_with_validation_error_in_service(self, client_logged, machine):
        """Daty odwrócone (end < start) → service rzuca ValidationError → 204."""
        response = client_logged.get(
            reverse("reservations:check_conflict"),
            {
                "machine": machine.pk,
                "start_date": "2030-01-10",
                "end_date": "2030-01-05",  # end < start → ValidationError
            },
        )
        assert response.status_code == 204


# =============================================================================
# Site update / delete — service ValidationError paths
# =============================================================================


@pytest.mark.django_db
class TestSiteUpdateValidationError:
    """site_update — service ValidationError → form errors."""

    def test_site_update_get_renders_form(self, client_logged, site):
        response = client_logged.get(reverse("reservations:site_update", args=[site.pk]))
        assert response.status_code == 200

    def test_site_update_invalid_dates(self, client_logged, site):
        """end_date < start_date → service ValidationError → 200 z form errors."""
        response = client_logged.post(
            reverse("reservations:site_update", args=[site.pk]),
            data={
                "project_number": site.project_number,
                "name": "Updated",
                "client_name": "",
                "address": site.address,
                "city": site.city or "Wwa",
                "status": "aktywna",
                "start_date": "2030-12-31",
                "end_date": "2030-01-01",  # end < start
                "notes": "",
            },
        )
        assert response.status_code == 200

    def test_site_update_success_redirect(self, client_logged, site):
        response = client_logged.post(
            reverse("reservations:site_update", args=[site.pk]),
            data={
                "project_number": site.project_number,
                "name": "Updated Name",
                "client_name": "Acme",
                "address": "ul. Nowa 1",
                "city": "Warszawa",
                "status": "aktywna",
                "start_date": "",
                "end_date": "",
                "notes": "Note",
            },
        )
        assert response.status_code == 302


@pytest.mark.django_db
class TestSiteDeleteValidationError:
    """site_delete — service ValidationError gdy site ma aktywne rezerwacje."""

    def test_delete_site_with_active_reservation_flashes_error(self, client_logged, site, machine):
        """Budowa z aktywną rezerwacją → service ValidationError → flash + redirect do detail."""
        ConfirmedReservationFactory(
            site=site,
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 10),
        )
        from reservations.models import ConstructionSite

        response = client_logged.post(reverse("reservations:site_delete", args=[site.pk]))
        assert response.status_code == 302
        # Budowa nadal istnieje
        assert ConstructionSite.objects.filter(pk=site.pk).exists()

    def test_delete_site_success(self, client_logged, site):
        from reservations.models import ConstructionSite

        response = client_logged.post(reverse("reservations:site_delete", args=[site.pk]))
        assert response.status_code == 302
        assert not ConstructionSite.objects.filter(pk=site.pk).exists()


# =============================================================================
# Site inline create — invalid form rerender
# =============================================================================


@pytest.mark.django_db
class TestSiteInlineCreateError:
    """site_inline_create — form invalid → re-render."""

    def test_inline_create_invalid_project_number(self, client_logged):
        """project_number missing → form invalid → 200 z form (not 204)."""
        response = client_logged.post(
            reverse("reservations:site_inline_create"),
            data={
                # Brak project_number — wymagane
                "name": "Inline",
                "address": "ul. X 1",
                "city": "Wwa",
            },
        )
        # Re-render formularza z błędem
        assert response.status_code == 200

    def test_inline_create_get_renders_form(self, client_logged):
        response = client_logged.get(reverse("reservations:site_inline_create"))
        assert response.status_code == 200


# =============================================================================
# QuickReserve — error paths
# =============================================================================


@pytest.mark.django_db
class TestQuickReserveErrorPaths:
    """QuickReserveView — wszystkie error-pathy."""

    def test_missing_machine_uid(self, client, user):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.post(
                reverse("reservations:quick_reserve"),
                data={"start_date": "2030-01-10"},
            )
            assert response.status_code == 200
            assert b"Brak wymaganych" in response.content

    def test_missing_start_date(self, client, user):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.post(
                reverse("reservations:quick_reserve"),
                data={"machine_uid": "KOP-001"},
            )
            assert response.status_code == 200
            assert b"Brak wymaganych" in response.content

    def test_invalid_date_format(self, client, user, machine):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.post(
                reverse("reservations:quick_reserve"),
                data={
                    "machine_uid": machine.uid,
                    "start_date": "not-a-date",
                },
            )
            assert response.status_code == 200
            assert b"Niepoprawny format daty" in response.content

    def test_machine_uid_not_found(self, client, user):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.post(
                reverse("reservations:quick_reserve"),
                data={
                    "machine_uid": "NONEXIST-999",
                    "start_date": "2030-01-10",
                },
            )
            assert response.status_code == 200
            assert b"nie istnieje" in response.content

    def test_quick_reserve_with_invalid_site_id(self, client, user, machine):
        """site_id='abc' → ValueError → site_id=None → service creates without site."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.post(
                reverse("reservations:quick_reserve"),
                data={
                    "machine_uid": machine.uid,
                    "start_date": "2030-01-10",
                    "end_date": "2030-01-12",
                    "person": "Tester",
                    "site_id": "not-a-number",
                },
            )
            # Sukces — fallback do None
            assert response.status_code == 200
            assert Reservation.objects.filter(machine=machine).exists()

    def test_quick_reserve_with_validation_error(self, client, user, machine):
        """Konflikt → service ValidationError → error partial."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            ConfirmedReservationFactory(
                machine=machine,
                start_date=date(2030, 1, 8),
                end_date=date(2030, 1, 15),
            )
            response = client.post(
                reverse("reservations:quick_reserve"),
                data={
                    "machine_uid": machine.uid,
                    "start_date": "2030-01-10",
                    "end_date": "2030-01-12",
                    "person": "Tester",
                },
            )
            assert response.status_code == 200
            # Komunikat o konflikcie
            body_low = response.content.lower()
            assert b"kolid" in body_low or b"konflikt" in body_low


# =============================================================================
# Timeline filter combinations
# =============================================================================


@pytest.mark.django_db
class TestTimelineFiltersExtra:
    """Pokrycie filter-combinations niepokrytych w `test_timeline.py`."""

    def test_timeline_with_machine_status_filter(self, client, user):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            Machine.objects.create(
                uid="WYC-1",
                name="Wycofana",
                machine_type=Machine.Type.KOPARKA,
                status=Machine.Status.WYCOFANA,
            )
            Machine.objects.create(
                uid="OK-1",
                name="OK",
                machine_type=Machine.Type.KOPARKA,
                status=Machine.Status.W_MAGAZYNIE,
            )
            # Explicit ?status=Wycofana — show ONLY wycofana
            response = client.get(reverse("reservations:timeline") + "?format=json&status=Wycofana")
            assert response.status_code == 200
            data = response.json()
            uids = [row["uid"] for row in data["machine_rows"]]
            assert "WYC-1" in uids
            assert "OK-1" not in uids

    def test_timeline_with_machine_type_and_status_combined(self, client, user):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            Machine.objects.create(
                uid="KP-1",
                name="K",
                machine_type=Machine.Type.KOPARKA,
                status=Machine.Status.WYCOFANA,
            )
            Machine.objects.create(
                uid="MN-1",
                name="M",
                machine_type=Machine.Type.MINIKOPARKA,
                status=Machine.Status.WYCOFANA,
            )
            response = client.get(
                reverse("reservations:timeline")
                + "?format=json&status=Wycofana&machine_type=koparka"
            )
            assert response.status_code == 200
            data = response.json()
            uids = [row["uid"] for row in data["machine_rows"]]
            assert "KP-1" in uids
            assert "MN-1" not in uids

    def test_timeline_with_bogus_period_falls_back(self, client, user):
        """?period=junk → fallback do 'week' bez 400."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.get(reverse("reservations:timeline") + "?format=json&period=junk")
            assert response.status_code == 200
            data = response.json()
            assert data["period"] == "week"

    def test_timeline_with_site_filter(self, client, user, machine, site):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            ConfirmedReservationFactory(
                machine=machine,
                site=site,
                start_date=date(2030, 1, 5),
                end_date=date(2030, 1, 8),
            )
            # Inna budowa
            from reservations.factories import ConstructionSiteFactory

            other_site = ConstructionSiteFactory(project_number="BUD-OTHER")
            machine2 = Machine.objects.create(
                uid="OO-1",
                name="Inna",
                machine_type=Machine.Type.KOPARKA,
                status=Machine.Status.W_MAGAZYNIE,
            )
            ConfirmedReservationFactory(
                machine=machine2,
                site=other_site,
                start_date=date(2030, 1, 5),
                end_date=date(2030, 1, 8),
            )
            response = client.get(
                reverse("reservations:timeline") + f"?format=json&site={site.project_number}"
            )
            data = response.json()
            # KOP-001 ma bar (site matches)
            rows = {r["uid"]: r for r in data["machine_rows"]}
            assert any(rows[r]["bars"] for r in rows if r == machine.uid)
            # OO-1 nie ma barów (site filter się nie zgadza)
            assert not rows["OO-1"]["bars"]

    def test_timeline_html_render_with_filters(self, client, user):
        """Timeline bez ?format=json → renderowany HTML template z filters_active."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.get(reverse("reservations:timeline") + "?search=KOP&person=test")
            # Status 200 — HTML render (filters_active=True), nie crash
            assert response.status_code == 200
            # filters_active jest True bo search+person podane
            assert response.context["filters_active"] is True

    def test_timeline_htmx_returns_grid_partial(self, client, user):
        """HTMX request → grid partial template (not full timeline.html)."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.get(
                reverse("reservations:timeline"),
                HTTP_HX_REQUEST="true",
            )
            assert response.status_code == 200

    def test_timeline_with_person_filter(self, client, user, machine):
        """?person=Anna → filtruje reservation.person__icontains."""
        with freeze_time("2030-01-05"):
            client.force_login(user)
            ConfirmedReservationFactory(
                machine=machine,
                person="Anna Test",
                start_date=date(2030, 1, 5),
                end_date=date(2030, 1, 8),
            )
            response = client.get(reverse("reservations:timeline") + "?format=json&person=Anna")
            data = response.json()
            rows = {r["uid"]: r for r in data["machine_rows"]}
            assert rows[machine.uid]["bars"]  # ma bar


# =============================================================================
# Reservation list filters — covering all data.get(...) branches
# =============================================================================


@pytest.mark.django_db
class TestReservationListFilters:
    """Pokrycie wszystkich branches filter_form w ReservationListView.get_queryset."""

    def test_filter_by_machine(self, client_logged, machine, second_machine):
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=second_machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        response = client_logged.get(reverse("reservations:list"), {"machine": machine.pk})
        assert response.status_code == 200
        assert len(response.context["reservations"]) == 1

    def test_filter_by_site(self, client_logged, machine, site):
        from reservations.factories import ConstructionSiteFactory

        other_site = ConstructionSiteFactory(project_number="BUD-NN-2026")
        ConfirmedReservationFactory(
            machine=machine,
            site=site,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=machine,
            site=other_site,
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        response = client_logged.get(reverse("reservations:list"), {"site": site.pk})
        assert response.status_code == 200
        assert len(response.context["reservations"]) == 1

    def test_filter_by_person_partial(self, client_logged, machine):
        ConfirmedReservationFactory(
            machine=machine,
            person="Anna Search",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=machine,
            person="Bartek X",
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 5),
        )
        response = client_logged.get(reverse("reservations:list"), {"person": "anna"})
        assert response.status_code == 200
        assert len(response.context["reservations"]) == 1

    def test_filter_by_start_after_and_end_before(self, client_logged, machine):
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        ConfirmedReservationFactory(
            machine=machine,
            start_date=date(2030, 6, 1),
            end_date=date(2030, 6, 5),
        )
        response = client_logged.get(
            reverse("reservations:list"),
            {"start_after": "2030-05-01", "end_before": "2030-12-31"},
        )
        assert response.status_code == 200
        assert len(response.context["reservations"]) == 1


# =============================================================================
# Site list filters
# =============================================================================


@pytest.mark.django_db
class TestSiteListFilters:
    """Pokrycie ?q= i ?status= w ConstructionSiteListView."""

    def test_site_list_query_filter(self, client_logged):
        from reservations.factories import ConstructionSiteFactory

        ConstructionSiteFactory(project_number="BUD-2026-AAA", name="Apartamenty")
        ConstructionSiteFactory(project_number="BUD-2026-BBB", name="Bunkry")
        response = client_logged.get(reverse("reservations:site_list"), {"q": "Apartamenty"})
        assert response.status_code == 200
        sites_in_ctx = list(response.context["sites"])
        names = [s.name for s in sites_in_ctx]
        assert "Apartamenty" in names
        assert "Bunkry" not in names

    def test_site_list_status_filter(self, client_logged):
        from reservations.factories import ConstructionSiteFactory
        from reservations.models import ConstructionSite

        ConstructionSiteFactory(project_number="BUD-A1", status=ConstructionSite.Status.AKTYWNA)
        ConstructionSiteFactory(project_number="BUD-Z1", status=ConstructionSite.Status.ZAKONCZONA)
        response = client_logged.get(
            reverse("reservations:site_list"),
            {"status": ConstructionSite.Status.ZAKONCZONA.value},
        )
        assert response.status_code == 200
        sites_in_ctx = list(response.context["sites"])
        statuses = [s.status for s in sites_in_ctx]
        assert all(s == ConstructionSite.Status.ZAKONCZONA for s in statuses)


# =============================================================================
# Site detail context
# =============================================================================


@pytest.mark.django_db
class TestSiteDetailContext:
    def test_site_detail_shows_reservations(self, client_logged, machine, site):
        ConfirmedReservationFactory(
            machine=machine,
            site=site,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        response = client_logged.get(reverse("reservations:site_detail", args=[site.pk]))
        assert response.status_code == 200
        # Context zawiera 'reservations' queryset (lazy z select_related)
        assert "reservations" in response.context
        assert len(list(response.context["reservations"])) == 1


# =============================================================================
# Site create — service VR error path
# =============================================================================


@pytest.mark.django_db
class TestSiteCreateValidationError:
    """site_create — service-level VR (duplicate project_number)."""

    def test_create_duplicate_project_number_returns_form(self, client_logged):
        from reservations.factories import ConstructionSiteFactory

        ConstructionSiteFactory(project_number="BUD-DUP-001")
        response = client_logged.post(
            reverse("reservations:site_create"),
            data={
                "project_number": "BUD-DUP-001",  # duplikat
                "name": "Test",
                "client_name": "",
                "address": "ul. Test 1",
                "city": "Wwa",
                "status": "aktywna",
                "start_date": "",
                "end_date": "",
                "notes": "",
            },
        )
        # Form re-rendered z błędem (200, NIE 302)
        assert response.status_code == 200


# =============================================================================
# HTMX create — success 204 path
# =============================================================================


@pytest.mark.django_db
class TestReservationCreateHTMX:
    """HTMX POST /rezerwacje/dodaj/ → 204 + HX-Trigger."""

    def test_htmx_create_returns_204_with_trigger(self, client, user, machine):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            future_start = date(2030, 1, 10)
            future_end = date(2030, 1, 15)
            response = client.post(
                reverse("reservations:create"),
                data={
                    "machine": machine.pk,
                    "site": "",
                    "start_date": future_start.isoformat(),
                    "end_date": future_end.isoformat(),
                    "person": "Anna Test",
                    # Wave 14-A Bundle 4 -- address + responsible_person wymagane.
                    "address": "Polna 5, Krakow",
                    "responsible_person": "Jan Kowalski",
                    "notes": "",
                },
                HTTP_HX_REQUEST="true",
            )
            assert response.status_code == 204
            # Bug 14 fix 2026-05-31: dodano "refreshTimeline" zeby tworzenie
            # z timeline'a HTMX-swap'owalo grid bez full page reload.
            assert response["HX-Trigger"] == "reservationCreated, refreshTimeline"

    def test_htmx_create_get_returns_partial(self, client, user):
        with freeze_time("2030-01-05"):
            client.force_login(user)
            response = client.get(
                reverse("reservations:create"),
                HTTP_HX_REQUEST="true",
            )
            assert response.status_code == 200
            # Partial bez DOCTYPE/<html> (form-only).
            assert b"<!DOCTYPE" not in response.content
            assert b"<html" not in response.content


# =============================================================================
# Confirm error path
# =============================================================================


@pytest.mark.django_db
class TestConfirmErrorPath:
    """confirm_reservation rzuca VR → flash error + redirect."""

    def test_confirm_already_completed_flashes_error(self, client_logged, machine):
        res = ConfirmedReservationFactory(
            machine=machine,
            status=Reservation.Status.ZAKONCZONA,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 5),
        )
        response = client_logged.post(reverse("reservations:confirm", args=[res.pk]))
        assert response.status_code == 302  # redirect z flash
        res.refresh_from_db()
        assert res.status == Reservation.Status.ZAKONCZONA  # bez zmian


# =============================================================================
# Batch bulk error paths — VR catch
# =============================================================================


@pytest.mark.django_db
class TestBatchBulkErrorPaths:
    """Pokrycie ValidationError branches w bulk_confirm/cancel/change_operator."""

    def test_bulk_confirm_with_invalid_batch_uuid_no_error(self, client_logged):
        """Random UUID → service zwraca 0 confirmed, 0 skipped → success flash."""
        import uuid

        random_id = uuid.uuid4()
        response = client_logged.post(
            reverse("reservations:batch_bulk_confirm", kwargs={"batch_id": random_id})
        )
        # Redirect (do nieistniejącego batch_detail → 404 follow, ale redirect status ok)
        assert response.status_code == 302

    def test_bulk_cancel_with_invalid_uuid_no_error(self, client_logged):
        import uuid

        random_id = uuid.uuid4()
        response = client_logged.post(
            reverse("reservations:batch_bulk_cancel", kwargs={"batch_id": random_id}),
            data={"cancellation_reason": "klient_zrezygnowal"},
        )
        assert response.status_code == 302

    def test_bulk_change_operator_with_invalid_uuid_no_error(self, client_logged):
        import uuid

        random_id = uuid.uuid4()
        response = client_logged.post(
            reverse("reservations:batch_bulk_change_operator", kwargs={"batch_id": random_id}),
            data={"new_person": "Anna"},
        )
        assert response.status_code == 302
