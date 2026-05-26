"""Views for the reservations app — reservations + construction sites.

Class-based views are used for the CRUD plumbing (less boilerplate) and a
handful of function-based views for the HTMX endpoints and POST-only state
transitions (cancel/confirm/complete) where a CBV adds no value.

HTMX integration:

* ``request.htmx`` (from ``django_htmx``) → return a partial template fragment
  instead of a full page render.
* :class:`CheckConflictView` is the live conflict-check endpoint used by the
  reservation form (`hx-trigger="change"` on machine + date fields).
* :class:`SiteInlineCreateView` lets the user create a new construction site
  without leaving the reservation form (modal flow).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, UpdateView, View

from core.service_errors import add_form_errors, join_validation_error
from core.utils import parse_iso_date
from machines.models import Machine

from .forms import (
    BatchCancelForm,
    BatchChangeOperatorForm,
    BatchReservationForm,
    ChangeOperatorForm,
    ConstructionSiteForm,
    ReservationFilterForm,
    ReservationForm,
    SwapMachineForm,
)
from .models import ConstructionSite, Reservation
from .services import (
    bulk_cancel_batch,
    bulk_change_operator_batch,
    bulk_confirm_batch,
    cancel_reservation,
    change_operator,
    complete_reservation,
    confirm_reservation,
    create_batch_reservation,
    create_reservation,
    create_site,
    delete_site,
    get_conflicting_reservations,
    report_breakdown,
    swap_machine,
    update_reservation,
    update_site,
)

logger = logging.getLogger("reservations")

PAGE_SIZE = 20


# =============================================================================
# RESERVATION — LIST + DETAIL
# =============================================================================


class ReservationListView(LoginRequiredMixin, ListView):
    """Paginated list of reservations with a sidebar filter form."""

    model = Reservation
    template_name = "reservations/list.html"
    context_object_name = "reservations"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        qs = Reservation.objects.select_related("machine", "site").order_by("-start_date")
        self.filter_form = ReservationFilterForm(self.request.GET or None)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data.get("q"):
                # F-5: enable search() manager (person | address | notes |
                # site.name | site.project_number). Subquery zamiast Q-expr
                # bezpośrednio w widoku — pozostaje source of truth w managerze.
                qs = qs.filter(pk__in=Reservation.objects.search(data["q"]).values("pk"))
            if data.get("status"):
                qs = qs.filter(status=data["status"])
            if data.get("machine"):
                qs = qs.filter(machine=data["machine"])
            if data.get("site"):
                qs = qs.filter(site=data["site"])
            if data.get("person"):
                qs = qs.filter(person__icontains=data["person"])
            if data.get("start_after"):
                qs = qs.filter(start_date__gte=data["start_after"])
            if data.get("end_before"):
                qs = qs.filter(end_date__lte=data["end_before"])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        ctx["today"] = date.today()
        return ctx

    def get_template_names(self):
        # HTMX requests get just the table fragment (used by filter form
        # ``hx-get`` to live-update the result list without a full reload).
        if getattr(self.request, "htmx", False):
            return ["reservations/_list_table.html"]
        return [self.template_name]


class ReservationDetailView(LoginRequiredMixin, DetailView):
    """Detail page for a single reservation."""

    model = Reservation
    template_name = "reservations/detail.html"
    context_object_name = "reservation"

    def get_queryset(self):
        # ``replaced_by`` doczepiamy select_related żeby render bannera
        # "Zastąpiona przez #N na KOP-002" nie wymagał dodatkowego query.
        return Reservation.objects.select_related(
            "machine", "site", "replaced_by", "replaced_by__machine"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # B-6 — modal "Wymień maszynę" potrzebuje queryset maszyn (wyklucza
        # obecną + WYCOFANA + W_SERWISIE). Bezsensowne renderować dropdown
        # gdy rezerwacja jest zamknięta — modal i tak nie pokaże się.
        if not self.object.is_closed:
            ctx["swap_machine_form"] = SwapMachineForm(current_machine_id=self.object.machine_id)
        return ctx


# =============================================================================
# Wave 14-A Bundle 2 + 3 — Timeline → Modal (full ReservationForm reuse 1:1)
# =============================================================================


@login_required
def reservation_modal_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Wave 14-A Bundle 2 — Timeline klik bar -> popup modal pelnej rezerwacji.

    Zwraca partial template (`_reservation_full_modal.html`) z ReservationForm
    pre-fill'owanym danymi istniejacej rezerwacji + pelny zestaw akcji
    (edytuj/anuluj/zakoncz/zmien-osobe).

    REUSE: identyczny ReservationForm jak na pelnej stronie /rezerwacje/<pk>/edytuj/
    -- klient widzi te same pola, te same widgety, te sam helper text.
    Form action wskazuje na `reservations:update` zeby submit szedl pelna
    sciezka POST + walidacja servicowa.

    HTMX-only endpoint: klient woła `hx-get`, server zwraca partial ktorego
    rodzic na timeline'u swapuje do <div id="reservation-modal-body">.
    """
    reservation = get_object_or_404(
        Reservation.objects.select_related("machine", "site", "replaced_by"),
        pk=pk,
    )
    form = ReservationForm(instance=reservation)
    return render(
        request,
        "reservations/_reservation_full_modal.html",
        {
            "form": form,
            "reservation": reservation,
            "mode": "edit",
        },
    )


@login_required
def reservation_quick_modal_view(request: HttpRequest) -> HttpResponse:
    """Wave 14-A Bundle 3 — Timeline klik PUSTY cell -> pelen ReservationForm w modalu.

    GET params: ``machine_uid`` (KOP-001) + ``day`` (ISO YYYY-MM-DD).
    Pre-selectuje maszyne (jesli istnieje) + start_date z clicked day +
    end_date = start_date + 14 dni (default). Reszta pol pusta -- user wpisuje.

    REUSE: ten sam ReservationForm jak Bundle 2 -- tylko w trybie "create"
    (no instance). Submit idzie do `reservations:create` ktore obsluguje
    HTMX + non-HTMX request'y.
    """
    machine_uid = (request.GET.get("machine_uid") or "").strip()
    day_raw = (request.GET.get("day") or "").strip()

    initial: dict = {}
    if day_raw:
        try:
            start_date = date.fromisoformat(day_raw)
            initial["start_date"] = start_date
            # Default 15 dni (Sebastian walkthrough -- typowy okres wynajmu).
            initial["end_date"] = start_date + timedelta(days=14)
        except ValueError:
            pass

    machine: Machine | None = None
    if machine_uid:
        try:
            machine = Machine.objects.get(uid=machine_uid)
            initial["machine"] = machine.pk
        except Machine.DoesNotExist:
            pass

    form = ReservationForm(initial=initial)
    # Wave 14-I fix: jesli klikneta maszyna ma status W_SERWISIE / WYCOFANA,
    # standardowy form queryset ja wyklucza -> dropdown pokazuje "---------"
    # zamiast preselected machine. Rozszerzamy queryset zeby user widzial
    # preselect ale moze ja zmienic na inna jesli chce.
    if machine is not None:
        existing = form.fields["machine"].queryset
        if not existing.filter(pk=machine.pk).exists():
            # Lista pkow zamiast | (unique-vs-non-unique TypeError w Django 5.2).
            allowed_pks = set(existing.values_list("pk", flat=True)) | {machine.pk}
            form.fields["machine"].queryset = Machine.objects.filter(pk__in=allowed_pks).order_by(
                "uid"
            )
    return render(
        request,
        "reservations/_reservation_full_modal.html",
        {
            "form": form,
            "reservation": None,  # tryb create
            "mode": "create",
            "preselect_machine_uid": machine_uid,
            "preselect_day": day_raw,
        },
    )


class ReservationPDFView(LoginRequiredMixin, View):
    """Generuje PDF rezerwacji do pobrania (A4 print do przyklejenia na maszynie).

    Wymaga zalogowania; każdy zalogowany użytkownik z dostępem do detail może
    pobrać PDF (taki sam scope read jak detail view).
    """

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        from .pdf import generate_reservation_pdf

        reservation = get_object_or_404(
            Reservation.objects.select_related("machine", "site"), pk=pk
        )
        pdf_bytes = generate_reservation_pdf(reservation)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="rezerwacja-{reservation.pk}.pdf"'
        return response


# =============================================================================
# RESERVATION — CREATE / UPDATE
# =============================================================================


@login_required
@permission_required("reservations.add_reservation", raise_exception=True)
def reservation_create(request: HttpRequest) -> HttpResponse:
    """Create a new reservation.

    Wymaga uprawnienia ``reservations.add_reservation`` — w domyślnym RBAC
    nadawane grupie "Magazynierzy" (i wszystkim wyższym). ``raise_exception=True``
    zwraca 403 zamiast redirectu do login (login_required już to ogarnia).

    Supports HTMX: a ``GET`` from inside a modal returns the form partial,
    a ``POST`` either succeeds (close modal + refresh list via ``HX-Trigger``)
    or returns the form with errors rendered in place.
    """
    if request.method == "POST":
        form = ReservationForm(request.POST)
        if form.is_valid():
            try:
                reservation = create_reservation(
                    machine_id=form.cleaned_data["machine"].pk,
                    site_id=(form.cleaned_data["site"].pk if form.cleaned_data["site"] else None),
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                    person=form.cleaned_data["person"],
                    address=form.cleaned_data.get("address", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    # Wave 14-A Bundle 4 -- responsible_person prop from form
                    responsible_person=form.cleaned_data.get("responsible_person", ""),
                    # Wave 14-H Bundle M-1: form-driven flow → service enforce'uje
                    # address + responsible_person (form sam też enforce'uje,
                    # ale defense-in-depth — formularz może być z bypass).
                    require_full_fields=True,
                )
            except ValidationError as exc:
                add_form_errors(form, exc)
            else:
                messages.success(
                    request,
                    _("Rezerwacja %(title)s została utworzona.") % {"title": reservation.title},
                )
                if getattr(request, "htmx", False):
                    # Close the modal + refresh the list table via HX-Trigger.
                    response = HttpResponse(status=204)
                    response["HX-Trigger"] = "reservationCreated"
                    return response
                return redirect("reservations:detail", pk=reservation.pk)
    else:
        form = ReservationForm()

    template = (
        "reservations/_form_partial.html"
        if getattr(request, "htmx", False)
        else "reservations/form.html"
    )
    return render(request, template, {"form": form, "mode": "create"})


def _normalize_person_name(name: str) -> str:
    """B-5: case-insensitive + accent-insensitive normalizacja imion.

    Przyklad: ``"Sven Olsén"`` → ``"sven olsen"``, więc ``"Sven Olsen"`` i
    ``"sven olsén"`` w bazie matchują do siebie. Implementuje NFKD decomposition
    (rozbija "é" na "e" + combining acute) i odrzuca non-ASCII bytes —
    standardowy unicode-folding pattern.

    Plan długofalowy (M3): pole ``Reservation.created_by = FK(User)`` zastąpi
    ten free-text fuzzy match — wtedy ta funkcja zniknie. Aktualnie magazynierka
    Sven Olsén z polskim akcentem nie mogła edytować rezerwacji wpisanej jako
    "Sven Olsen" w innym systemie (regression podczas migracji M1→M2).
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ASCII", "ignore").decode()
    return ascii_only.casefold().strip()


class ReservationUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Edit an existing reservation.

    Wymaga uprawnienia ``reservations.change_reservation``. Non-superuserowie
    widzą tylko swoje rezerwacje (queryset filtered by ``person``); superuser
    widzi wszystkie. ``raise_exception=True`` daje 403 zamiast cichego redirectu.

    B-5: ownership match jest case-insensitive + accent-insensitive — dzięki
    temu "Sven Olsén" (z akcentem) matchuje rezerwację wpisaną jako "Sven Olsen"
    (bez akcentu) i odwrotnie. Patrz :func:`_normalize_person_name`.
    """

    model = Reservation
    form_class = ReservationForm
    template_name = "reservations/form.html"
    context_object_name = "reservation"
    permission_required = "reservations.change_reservation"
    raise_exception = True

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_superuser:
            return qs
        # Ownership check — non-superuser może edytować tylko swoje rezerwacje.
        # ``person`` jest free-text (M2 limitation) — porównujemy do
        # get_full_name() albo username (fallback gdy profil pusty).
        #
        # B-5: case+accent-insensitive matching. Robimy w Pythonie (nie w SQL)
        # bo SQLite nie ma natywnego unaccent extension, a Postgres pg_trgm
        # różnie się zachowuje per-instalacja. Filtr per-row jest O(N) ale
        # N==(user's reservations) jest małe (~10-100), więc OK na M2.
        # Plan M3: FK ``created_by`` → zniknie cały ten kod.
        full_name = self.request.user.get_full_name() or self.request.user.get_username()
        target = _normalize_person_name(full_name)
        if not target:
            return qs.none()
        matching_pks = [
            r.pk for r in qs.only("pk", "person") if _normalize_person_name(r.person) == target
        ]
        return qs.filter(pk__in=matching_pks)

    def form_valid(self, form):
        try:
            update_reservation(
                self.object,
                start_date=form.cleaned_data["start_date"],
                end_date=form.cleaned_data["end_date"],
                person=form.cleaned_data["person"],
                address=form.cleaned_data.get("address", ""),
                notes=form.cleaned_data.get("notes", ""),
                site_id=(form.cleaned_data["site"].pk if form.cleaned_data["site"] else None),
                # Wave 14-A Bundle 4 -- responsible_person editable in update
                responsible_person=form.cleaned_data.get("responsible_person", ""),
            )
        except ValidationError as exc:
            add_form_errors(form, exc)
            return self.form_invalid(form)

        messages.success(self.request, _("Rezerwacja zaktualizowana."))
        return redirect("reservations:detail", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mode"] = "edit"
        return ctx


# =============================================================================
# RESERVATION — STATE TRANSITIONS
# =============================================================================


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def reservation_confirm(request: HttpRequest, pk: int) -> HttpResponse:
    """Promuje rezerwację z OCZEKUJACA do POTWIERDZONA.

    Wymaga uprawnienia ``reservations.change_reservation`` — domyślnie
    grupa "Magazynierzy" + "Kierownicy".
    """
    reservation = get_object_or_404(Reservation, pk=pk)
    try:
        confirm_reservation(reservation)
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(request, _("Rezerwacja potwierdzona."))
    return redirect("reservations:detail", pk=pk)


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def reservation_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    """Anuluje rezerwację (OCZEKUJACA / POTWIERDZONA → ANULOWANA).

    B-2 — wymaga POST z polem ``cancellation_reason`` (jedna z
    :attr:`Reservation.CancellationReason` choices) + opcjonalna
    ``cancellation_note``. Service rzuca ValidationError jeśli reason pusty
    lub nieznany — view tłumaczy na flash error + redirect.

    Wymaga uprawnienia ``reservations.change_reservation``.
    """
    reservation = get_object_or_404(Reservation, pk=pk)
    reason = (request.POST.get("cancellation_reason") or "").strip()
    # Wave 11 M-2 fix: max_length=500 zapobiega DoS via storage
    # (TextField bez limitu może przyjąć dowolnie duży payload).
    note = (request.POST.get("cancellation_note") or "")[:500]
    try:
        cancel_reservation(reservation, reason=reason, note=note)
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(request, _("Rezerwacja anulowana."))
    return redirect("reservations:detail", pk=pk)


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def reservation_complete(request: HttpRequest, pk: int) -> HttpResponse:
    """Kończy rezerwację (POTWIERDZONA → ZAKONCZONA) i zwraca maszynę.

    B-3 — opcjonalny POST field ``actual_return_date`` (ISO yyyy-mm-dd).
    Jeśli ustawione, ustawia ``Reservation.actual_return_date`` (zapis w
    services), co zwalnia maszynę w ``has_conflict`` na kolejne dni.
    Brak pola = brak zmiany ``actual_return_date`` (default dzisiejszy
    zwrot zgodnie z legacy zachowaniem).

    Wymaga uprawnienia ``reservations.change_reservation``.
    """
    reservation = get_object_or_404(Reservation, pk=pk)
    actual_return_raw = (request.POST.get("actual_return_date") or "").strip()
    actual_return: date | None = parse_iso_date(actual_return_raw) if actual_return_raw else None
    try:
        complete_reservation(reservation, actual_return_date=actual_return)
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(request, _("Rezerwacja zakończona, maszyna wróciła do magazynu."))
    return redirect("reservations:detail", pk=pk)


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def reservation_change_operator(request: HttpRequest, pk: int) -> HttpResponse:
    """B-4 — zmiana osoby rezerwacji bez tworzenia nowej.

    Magazynierka w modalu wpisuje "Sven Olsen" → POST → service
    :func:`change_operator` mutuje pole ``person`` (audit via simple-history).
    Bez side-effectów na maszynę / daty / status.

    Wymaga uprawnienia ``reservations.change_reservation`` (ta sama grupa
    co confirm/cancel/complete/awaria).
    """
    reservation = get_object_or_404(Reservation, pk=pk)
    form = ChangeOperatorForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Niepoprawne dane: %(err)s") % {"err": form.errors.as_text()})
        return redirect("reservations:detail", pk=pk)
    try:
        change_operator(
            reservation,
            new_person=form.cleaned_data["new_person"],
            actor=request.user,
        )
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(
            request,
            _("Osoba zmieniona na: %(person)s") % {"person": form.cleaned_data["new_person"]},
        )
    return redirect("reservations:detail", pk=pk)


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def reservation_swap_machine(request: HttpRequest, pk: int) -> HttpResponse:
    """B-6 — wymiana maszyny mid-reservation.

    Magazynierka w modalu wybiera maszynę zastępczą + opcjonalny powód →
    POST → service :func:`swap_machine`:
      * zamyka oryginalną rezerwację dziś (status ZAKONCZONA, notatka),
      * tworzy nową rezerwację POTWIERDZONA na zastępczej maszynie pokrywającą
        pozostały okres, z preserved ``person`` / ``site`` / ``address``,
      * (best-effort) przesuwa starą maszynę do W_SERWISIE,
      * ustawia FK ``replaced_by`` z oryginalnej do nowej (audit).

    Wymaga uprawnienia ``reservations.change_reservation``.
    """
    reservation = get_object_or_404(Reservation, pk=pk)
    form = SwapMachineForm(request.POST, current_machine_id=reservation.machine_id)
    if not form.is_valid():
        messages.error(request, _("Niepoprawne dane: %(err)s") % {"err": form.errors.as_text()})
        return redirect("reservations:detail", pk=pk)
    try:
        result = swap_machine(
            reservation,
            new_machine=form.cleaned_data["new_machine"],
            reason=form.cleaned_data.get("reason", ""),
            actor=request.user,
        )
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
        return redirect("reservations:detail", pk=pk)

    messages.success(
        request,
        _("Maszyna wymieniona — nowa rezerwacja #%(new_id)s na %(uid)s utworzona.")
        % {
            "new_id": result["new_id"],
            "uid": form.cleaned_data["new_machine"].uid,
        },
    )
    # Po wymianie przekierowujemy na NOWĄ rezerwację — to ona jest teraz
    # aktywna (oryginalna staje się historyczna z banerem "Zastąpiona").
    return redirect("reservations:detail", pk=result["new_id"])


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def reservation_report_breakdown(request: HttpRequest, pk: int) -> HttpResponse:
    """One-click flow "Zgłoś awarię" — patrz :func:`services.report_breakdown`.

    Magazynierka klika 1 button na detail page → rezerwacja zostaje
    zamknięta dziś + maszyna trafia do serwisu + tworzy się wpis
    ``ServiceRecord`` typu "naprawa" z opisem awarii podanym w modalu.

    Wymaga ``reservations.change_reservation`` (ta sama grupa co
    confirm/cancel/complete). Brak opisu / opis za krótki = flash error
    + redirect do detail bez side-effectów.
    """
    reservation = get_object_or_404(Reservation, pk=pk)
    description = request.POST.get("description", "")
    try:
        result = report_breakdown(reservation, description=description, actor=request.user)
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(
            request,
            _("Awaria zgłoszona — maszyna %(uid)s w serwisie, rezerwacja zamknięta.")
            % {"uid": result["machine_uid"]},
        )
    return redirect("reservations:detail", pk=pk)


# =============================================================================
# RESERVATION — HTMX HELPERS
# =============================================================================


def _safe_int(raw: str | None) -> int | None:
    """Parsuje int, zwraca ``None`` przy błędzie.

    Drobna pomocnicza analogiczna do :func:`core.utils.parse_iso_date` —
    wyodrębniona aby trzymać try/except poza ścieżką szczęśliwą widoku.
    """
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class CheckConflictView(LoginRequiredMixin, View):
    """HTMX-only endpoint that pre-checks a reservation for conflicts.

    Called by the create/edit form on ``change`` of the machine / date inputs.
    Returns either an empty 204 response (no conflict) or an HTML partial
    describing the conflicting bookings.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        machine_id = _safe_int(request.GET.get("machine"))
        start = parse_iso_date(request.GET.get("start_date"))
        end = parse_iso_date(request.GET.get("end_date"))
        if machine_id is None or start is None or end is None:
            return HttpResponse(status=204)

        exclude_pk_raw = request.GET.get("exclude_pk")
        exclude_pk: int | None = None
        if exclude_pk_raw:
            try:
                exclude_pk = int(exclude_pk_raw)
            except ValueError:
                exclude_pk = None

        try:
            conflicts = get_conflicting_reservations(
                machine_id=machine_id, start=start, end=end, exclude_pk=exclude_pk
            )
        except ValidationError:
            return HttpResponse(status=204)

        if not conflicts:
            return HttpResponse(status=204)
        return render(
            request,
            "reservations/_conflict_warning.html",
            {"conflicts": conflicts},
        )


# =============================================================================
# CONSTRUCTION SITE — LIST / DETAIL / CRUD
# =============================================================================


class ConstructionSiteListView(LoginRequiredMixin, ListView):
    model = ConstructionSite
    template_name = "reservations/site_list.html"
    context_object_name = "sites"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        # Annotacja ``active_reservations_count`` (oczekujące + potwierdzone)
        # jednym JOIN-em zamiast N+1 (po jednym ``COUNT(*)`` na budowę).
        # Nazwa różni się od istniejącej ``@property active_reservation_count``
        # (single „reservation") — Django nie pozwala adnotacji nadpisać pola
        # / property bez settera.
        qs = ConstructionSite.objects.annotate(
            active_reservations_count=Count(
                "reservations",
                filter=Q(
                    reservations__status__in=(
                        Reservation.Status.OCZEKUJACA,
                        Reservation.Status.POTWIERDZONA,
                    )
                ),
            ),
        ).order_by("-created_at")
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
                | Q(project_number__icontains=query)
                | Q(client_name__icontains=query)
                | Q(city__icontains=query)
            )
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["query"] = self.request.GET.get("q", "")
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["statuses"] = ConstructionSite.Status.choices
        return ctx


class ConstructionSiteDetailView(LoginRequiredMixin, DetailView):
    model = ConstructionSite
    template_name = "reservations/site_detail.html"
    context_object_name = "site"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["reservations"] = self.object.reservations.select_related("machine").order_by(
            "-start_date"
        )
        return ctx


@login_required
@permission_required("reservations.add_constructionsite", raise_exception=True)
def site_create(request: HttpRequest) -> HttpResponse:
    """Tworzy nową budowę (ConstructionSite).

    Wave 4 P0: wcześniej tylko ``login_required`` — KAŻDY zalogowany user
    mógł tworzyć budowy, co prowadziło do śmietnika w pre-prod. Wymaga
    teraz uprawnienia ``reservations.add_constructionsite`` (Magazynierzy/
    Kierownicy/Administratorzy w setup_groups).
    """
    if request.method == "POST":
        form = ConstructionSiteForm(request.POST)
        if form.is_valid():
            try:
                site = create_site(**form.cleaned_data)
            except ValidationError as exc:
                add_form_errors(form, exc)
            else:
                messages.success(
                    request,
                    _("Budowa %(project_number)s została utworzona.")
                    % {"project_number": site.project_number},
                )
                return redirect("reservations:site_detail", pk=site.pk)
    else:
        form = ConstructionSiteForm()
    return render(request, "reservations/site_form.html", {"form": form, "mode": "create"})


@login_required
@permission_required("reservations.change_constructionsite", raise_exception=True)
def site_update(request: HttpRequest, pk: int) -> HttpResponse:
    site = get_object_or_404(ConstructionSite, pk=pk)
    if request.method == "POST":
        form = ConstructionSiteForm(request.POST, instance=site, editable_project_number=False)
        if form.is_valid():
            try:
                update_site(
                    site,
                    name=form.cleaned_data["name"],
                    client_name=form.cleaned_data.get("client_name", ""),
                    address=form.cleaned_data["address"],
                    city=form.cleaned_data.get("city", ""),
                    status=form.cleaned_data["status"],
                    start_date=form.cleaned_data.get("start_date"),
                    end_date=form.cleaned_data.get("end_date"),
                    notes=form.cleaned_data.get("notes", ""),
                )
            except ValidationError as exc:
                add_form_errors(form, exc)
            else:
                messages.success(
                    request,
                    _("Budowa %(project_number)s zaktualizowana.")
                    % {"project_number": site.project_number},
                )
                return redirect("reservations:site_detail", pk=site.pk)
    else:
        form = ConstructionSiteForm(instance=site, editable_project_number=False)
    return render(
        request, "reservations/site_form.html", {"form": form, "mode": "edit", "site": site}
    )


@login_required
@require_POST
@permission_required("reservations.delete_constructionsite", raise_exception=True)
def site_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Usuwa budowę.

    Wave 4 P0: wcześniej tylko ``login_required`` — każdy zalogowany user
    mógł usunąć dowolną budowę (jeśli nie miała aktywnych rezerwacji).
    Wymaga teraz ``reservations.delete_constructionsite`` (default tylko
    Kierownicy/Administratorzy, nie Magazynierzy).
    """
    site = get_object_or_404(ConstructionSite, pk=pk)
    project_number = site.project_number
    try:
        delete_site(site)
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
        return redirect("reservations:site_detail", pk=pk)
    messages.success(
        request,
        _("Budowa %(project_number)s została usunięta.") % {"project_number": project_number},
    )
    return redirect("reservations:site_list")


@login_required
@permission_required("reservations.add_constructionsite", raise_exception=True)
def site_inline_create(request: HttpRequest) -> HttpResponse:
    """HTMX modal to create a new site without leaving the reservation form.

    On success returns 204 + ``HX-Trigger: siteCreated`` so the parent form
    can reload its ``site`` dropdown via ``hx-get``. On error re-renders the
    partial with the form errors.
    """
    if request.method == "POST":
        # Inline modal renderuje tylko 5 podstawowych pól (project_number, name,
        # client_name, address, city). Pozostałe pola form (status, daty, notes)
        # uzupełniamy defaultami z modelu — inline create to "szybki shortcut",
        # pełną edycję user robi przez /rezerwacje/budowy/<pk>/edytuj/.
        post_data = request.POST.copy()
        if not post_data.get("status"):
            post_data["status"] = ConstructionSite.Status.AKTYWNA
        form = ConstructionSiteForm(post_data)
        if form.is_valid():
            try:
                site = create_site(**form.cleaned_data)
            except ValidationError as exc:
                add_form_errors(form, exc)
            else:
                response = HttpResponse(status=204)
                response["HX-Trigger"] = json.dumps(
                    {"siteCreated": {"pk": site.pk, "label": str(site)}}
                )
                return response
    else:
        form = ConstructionSiteForm()
    return render(
        request,
        "reservations/_site_inline_create.html",
        {"form": form},
    )


# =============================================================================
# TIMELINE  (Gantt-style view of reservations per machine row x day column)
# =============================================================================

# Supported period strings → number of days rendered in one viewport.
# Centralised so the navigation helpers and the date-range computation use
# the same source of truth.
TIMELINE_PERIODS: dict[str, int] = {"week": 7, "2week": 14, "month": 30}
DEFAULT_TIMELINE_PERIOD = "week"

# Statuses considered "visible" on the timeline. Cancelled bookings would
# only add visual noise, confirmed/pending/completed give the planner the
# full picture of where each machine is (or has been recently).
_TIMELINE_VISIBLE_STATUSES: tuple[str, ...] = (
    Reservation.Status.OCZEKUJACA,
    Reservation.Status.POTWIERDZONA,
    Reservation.Status.ZAKONCZONA,
)


class TimelineView(LoginRequiredMixin, View):
    """Gantt-style timeline of reservations (machines by days).

    Query parameters:

    * ``period`` — ``week`` (default), ``2week``, ``month``.
    * ``start`` — ISO date for the first column (default: today).
    * ``machine_type`` — single machine type code; filters rows.
    * ``status`` — single machine status; filters rows.
    * ``site`` — :attr:`ConstructionSite.project_number`; filters bars.
    * ``person`` — case-insensitive substring; filters bars.
    * ``search`` — case-insensitive substring matched against machine
      ``name`` / ``uid``; filters rows.
    * ``format`` — ``html`` (default) or ``json`` (used by Alpine.js to
      hydrate the client-side store without rendering the template).

    The view is intentionally read-only — quick-reservation creation lives
    in :class:`QuickReserveView` so the HTMX cells can post directly to it.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        period = request.GET.get("period", DEFAULT_TIMELINE_PERIOD)
        days = TIMELINE_PERIODS.get(period, TIMELINE_PERIODS[DEFAULT_TIMELINE_PERIOD])
        # If a bogus ``period`` slips in we silently coerce it to the default
        # so the URL is still navigable (no 400 / no crash).
        if period not in TIMELINE_PERIODS:
            period = DEFAULT_TIMELINE_PERIOD

        start = parse_iso_date(request.GET.get("start"), date.today())
        end = start + timedelta(days=days - 1)
        day_list = [start + timedelta(days=i) for i in range(days)]

        # ----------------------------- row filter (machines) -----------------
        # Wave 4 P0: wykluczamy maszyny WYCOFANA z timeline — nie mają już
        # rezerwacji (forma + service guard) i pokazywałyby się jako "duchy"
        # bez bars w grid. Filter ?status= może ją explicit pokazać (admin
        # może chcieć historię), ale domyślnie ukrywamy.
        machines_qs = Machine.objects.exclude(status=Machine.Status.WYCOFANA)
        machine_type = request.GET.get("machine_type")
        if machine_type:
            machines_qs = machines_qs.filter(machine_type=machine_type)
        machine_status = request.GET.get("status")
        if machine_status:
            # Jeśli user explicit filtruje po WYCOFANA, nadpisujemy default exclude.
            machines_qs = Machine.objects.filter(status=machine_status)
            if machine_type:
                machines_qs = machines_qs.filter(machine_type=machine_type)
        search = (request.GET.get("search") or "").strip()
        if search:
            machines_qs = machines_qs.filter(Q(name__icontains=search) | Q(uid__icontains=search))

        # ----------------------------- bar filter (reservations) -------------
        reservations_qs = (
            Reservation.objects.for_period(start, end)
            .filter(status__in=_TIMELINE_VISIBLE_STATUSES)
            .select_related("site")
        )
        site_number = request.GET.get("site")
        if site_number:
            reservations_qs = reservations_qs.filter(site__project_number=site_number)
        person_q = (request.GET.get("person") or "").strip()
        if person_q:
            reservations_qs = reservations_qs.filter(person__icontains=person_q)

        # One Prefetch ⇒ all rows are filled in a single extra query, the
        # bars are read off ``machine.period_reservations`` (in-memory list).
        machines_qs = machines_qs.prefetch_related(
            Prefetch(
                "reservations",
                queryset=reservations_qs,
                to_attr="period_reservations",
            )
        ).order_by("uid")

        machine_rows: list[dict] = []
        for machine in machines_qs:
            bars: list[dict] = []
            for res in machine.period_reservations:
                # Clip the bar to the visible window so a reservation that
                # starts before / ends after the viewport still draws.
                bar_start = max(res.start_date, start)
                bar_end = min(res.end_date, end)
                offset_days = (bar_start - start).days
                length_days = (bar_end - bar_start).days + 1
                bars.append(
                    {
                        "id": res.pk,
                        "machine_uid": machine.uid,
                        "site_number": res.site.project_number if res.site_id else "",
                        "site_name": res.site.name if res.site_id else "",
                        "person": res.person,
                        "status": res.status,
                        "status_display": res.get_status_display(),
                        "start_date": res.start_date.isoformat(),
                        "end_date": res.end_date.isoformat(),
                        "offset_days": offset_days,
                        "length_days": length_days,
                        "url_detail": reverse("reservations:detail", kwargs={"pk": res.pk}),
                    }
                )
            machine_rows.append(
                {
                    "uid": machine.uid,
                    "name": machine.name,
                    "machine_type": machine.machine_type,
                    "machine_type_display": machine.get_machine_type_display(),
                    "status": machine.status,
                    "inspection_status": machine.inspection_status,
                    "bars": bars,
                }
            )

        # ?format=json — Alpine.js hydration endpoint. Returned without the
        # template so a JS client can refresh just the bars after a quick
        # reservation succeeds. Kept JSON-flat (no nested ORM dumps).
        if request.GET.get("format") == "json":
            return JsonResponse(
                {
                    "period": period,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "day_list": [d.isoformat() for d in day_list],
                    "machine_rows": machine_rows,
                }
            )

        filters_active = any(
            request.GET.get(k) for k in ("machine_type", "status", "site", "person", "search")
        )

        context = {
            "period": period,
            "days": days,
            "start": start,
            "end": end,
            "day_list": day_list,
            "machine_rows": machine_rows,
            "machine_types": Machine.Type.choices,
            "statuses": Machine.Status.choices,
            "sites": ConstructionSite.objects.filter(
                status=ConstructionSite.Status.AKTYWNA
            ).order_by("project_number"),
            "prev_start": (start - timedelta(days=days)).isoformat(),
            "next_start": (start + timedelta(days=days)).isoformat(),
            "today_iso": date.today().isoformat(),
            "filters_active": filters_active,
            # Echo current filter values so the template can pre-fill inputs.
            "current_machine_type": machine_type or "",
            "current_status": machine_status or "",
            "current_site": site_number or "",
            "current_person": person_q,
            "current_search": search,
        }

        template = (
            "reservations/_timeline_grid.html"
            if getattr(request, "htmx", False)
            else "reservations/timeline.html"
        )
        return render(request, template, context)


class QuickReserveView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """HTMX endpoint that creates a reservation from a single timeline cell.

    Wymaga uprawnienia ``reservations.add_reservation``. Bez tego dowolny
    zalogowany użytkownik mógłby tworzyć rezerwacje z poziomu timeline'a —
    co byłoby obejściem :func:`reservation_create` decoratora.

    The client posts ``machine_uid`` + ``start_date`` (+ optional ``end_date``,
    ``person``, ``site_id``). On success we return a tiny success partial
    plus an ``HX-Trigger`` that tells the surrounding page to refresh the
    timeline. On a conflict / validation error we render an error partial
    with a 200 (so HTMX swaps it in place instead of failing the request).
    """

    permission_required = "reservations.add_reservation"
    raise_exception = True

    def post(self, request: HttpRequest) -> HttpResponse:
        machine_uid = (request.POST.get("machine_uid") or "").strip()
        start_raw = request.POST.get("start_date")
        end_raw = request.POST.get("end_date") or start_raw
        person = (
            (request.POST.get("person") or "").strip()
            or request.user.get_full_name()
            or request.user.get_username()
        )
        site_id_raw = request.POST.get("site_id") or ""
        try:
            site_id: int | None = int(site_id_raw) if site_id_raw else None
        except ValueError:
            site_id = None

        if not machine_uid or not start_raw:
            return render(
                request,
                "reservations/_quick_reserve_error.html",
                {"error": _("Brak wymaganych pól: maszyna i data początku.")},
            )

        try:
            start_date = date.fromisoformat(start_raw)
            end_date = date.fromisoformat(end_raw)
        except ValueError:
            return render(
                request,
                "reservations/_quick_reserve_error.html",
                {"error": _("Niepoprawny format daty (oczekiwany YYYY-MM-DD).")},
            )

        try:
            machine = Machine.objects.get(uid=machine_uid)
        except Machine.DoesNotExist:
            return render(
                request,
                "reservations/_quick_reserve_error.html",
                {"error": _("Maszyna o UID %(uid)s nie istnieje.") % {"uid": machine_uid}},
            )

        try:
            reservation = create_reservation(
                machine_id=machine.pk,
                site_id=site_id,
                start_date=start_date,
                end_date=end_date,
                person=person,
            )
        except ValidationError as exc:
            return render(
                request,
                "reservations/_quick_reserve_error.html",
                {"error": join_validation_error(exc)},
            )

        response = render(
            request,
            "reservations/_quick_reserve_success.html",
            {"reservation": reservation},
        )
        response["HX-Trigger"] = json.dumps(
            {
                "refreshTimeline": True,
                "showToast": {
                    "message": str(
                        _("Rezerwacja %(uid)s utworzona.") % {"uid": reservation.machine.uid}
                    ),
                    "level": "success",
                },
            }
        )
        return response


# =============================================================================
# B-7 — BATCH RESERVATION (multi-maszynowa)
# =============================================================================


@login_required
@permission_required("reservations.add_reservation", raise_exception=True)
def batch_create_view(request: HttpRequest) -> HttpResponse:
    """B-7 — formularz tworzenia grupy rezerwacji (multi-machine).

    GET: renderuje :class:`BatchReservationForm`.
    POST: waliduje form → wywołuje :func:`services.create_batch_reservation`.
    Sukces → redirect do :func:`batch_detail_view`. Błąd service'a (konflikt,
    status maszyny, limit) → re-render form z błędami przez
    :func:`core.service_errors.add_form_errors`.

    Wymaga uprawnienia ``reservations.add_reservation`` (ta sama grupa co
    pojedyncza :func:`reservation_create`).
    """
    if request.method == "POST":
        form = BatchReservationForm(request.POST)
        if form.is_valid():
            try:
                result = create_batch_reservation(
                    machine_ids=[m.pk for m in form.cleaned_data["machines"]],
                    site_id=(form.cleaned_data["site"].pk if form.cleaned_data["site"] else None),
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                    person=form.cleaned_data["person"],
                    address=form.cleaned_data.get("address", ""),
                    notes=form.cleaned_data.get("notes", ""),
                )
            except ValidationError as exc:
                add_form_errors(form, exc)
            else:
                messages.success(
                    request,
                    _("Utworzono %(n)d rezerwacji w grupie (ID: %(short)s).")
                    % {
                        "n": result["created_count"],
                        "short": result["batch_id"][:8],
                    },
                )
                return redirect("reservations:batch_detail", batch_id=result["batch_id"])
    else:
        form = BatchReservationForm()
    return render(request, "reservations/batch_form.html", {"form": form})


@login_required
def batch_detail_view(request: HttpRequest, batch_id: uuid.UUID) -> HttpResponse:
    """B-7 — szczegóły grupy rezerwacji z bulk-action UI.

    Wyświetla wszystkie rezerwacje należące do grupy o danym ``batch_id``,
    pogrupowane po maszynach, z trzema bulk-action formami:
      * Potwierdź wszystkie (OCZEKUJACA → POTWIERDZONA),
      * Anuluj wszystkie (z wymaganym powodem),
      * Zmień operatora wszystkich (wpisz nowe imię i nazwisko).

    404 jeśli batch_id nie istnieje (żadnej rezerwacji o tym UUID).
    """
    reservations = list(
        Reservation.objects.filter(batch_id=batch_id)
        .select_related("machine", "site")
        .order_by("machine__uid")
    )
    if not reservations:
        raise Http404(_("Grupa rezerwacji nie istnieje."))

    # Stats agreguje liczbę per-status — używane w nagłówku + decide czy
    # bulk-confirm/cancel button mają sens (disable gdy 0 aktywnych).
    status_counts = {
        Reservation.Status.OCZEKUJACA: 0,
        Reservation.Status.POTWIERDZONA: 0,
        Reservation.Status.ZAKONCZONA: 0,
        Reservation.Status.ANULOWANA: 0,
    }
    for res in reservations:
        status_counts[res.status] = status_counts.get(res.status, 0) + 1

    representative = reservations[0]  # do nagłówka (osoba/site/daty są wspólne)
    has_pending = status_counts[Reservation.Status.OCZEKUJACA] > 0
    has_active = (
        status_counts[Reservation.Status.OCZEKUJACA]
        + status_counts[Reservation.Status.POTWIERDZONA]
        > 0
    )

    context = {
        "batch_id": batch_id,
        "batch_id_short": str(batch_id)[:8],
        "reservations": reservations,
        "representative": representative,
        "status_counts": status_counts,
        "total_count": len(reservations),
        "has_pending": has_pending,
        "has_active": has_active,
        "cancel_form": BatchCancelForm(),
        "change_operator_form": BatchChangeOperatorForm(),
    }
    return render(request, "reservations/batch_detail.html", context)


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def batch_bulk_confirm(request: HttpRequest, batch_id: uuid.UUID) -> HttpResponse:
    """B-7 — bulk potwierdź wszystkie OCZEKUJACA rezerwacje w grupie.

    Wywołuje :func:`services.bulk_confirm_batch` — pozostałe statusy
    skipped. Konflikt race-time → ValidationError → flash error, redirect
    z powrotem do batch_detail.
    """
    try:
        result = bulk_confirm_batch(batch_id, actor=request.user)
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(
            request,
            _("Potwierdzono %(n)d rezerwacji w grupie (pominięto %(s)d).")
            % {"n": result["confirmed_count"], "s": result["skipped_count"]},
        )
    return redirect("reservations:batch_detail", batch_id=batch_id)


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def batch_bulk_cancel(request: HttpRequest, batch_id: uuid.UUID) -> HttpResponse:
    """B-7 — bulk anuluj wszystkie aktywne rezerwacje w grupie.

    POST data: ``cancellation_reason`` (z choices) + opcjonalna ``cancellation_note``.
    Wywołuje :func:`services.bulk_cancel_batch` na całej grupie atomicznie.
    """
    form = BatchCancelForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _("Niepoprawne dane: %(err)s") % {"err": form.errors.as_text()},
        )
        return redirect("reservations:batch_detail", batch_id=batch_id)
    try:
        result = bulk_cancel_batch(
            batch_id,
            reason=form.cleaned_data["cancellation_reason"],
            note=form.cleaned_data.get("cancellation_note", ""),
            actor=request.user,
        )
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(
            request,
            _("Anulowano %(n)d rezerwacji w grupie (pominięto %(s)d).")
            % {"n": result["cancelled_count"], "s": result["skipped_count"]},
        )
    return redirect("reservations:batch_detail", batch_id=batch_id)


@login_required
@permission_required("reservations.change_reservation", raise_exception=True)
@require_POST
def batch_bulk_change_operator(request: HttpRequest, batch_id: uuid.UUID) -> HttpResponse:
    """B-7 — bulk zmień operatora wszystkich aktywnych rezerwacji w grupie.

    POST data: ``new_person`` (string, min 3 znaki).
    Wywołuje :func:`services.bulk_change_operator_batch` z audit trail
    przez ``simple-history`` (każda zmiana per-rezerwacja loguje actor'a).
    """
    form = BatchChangeOperatorForm(request.POST)
    if not form.is_valid():
        messages.error(
            request,
            _("Niepoprawne dane: %(err)s") % {"err": form.errors.as_text()},
        )
        return redirect("reservations:batch_detail", batch_id=batch_id)
    try:
        result = bulk_change_operator_batch(
            batch_id,
            new_person=form.cleaned_data["new_person"],
            actor=request.user,
        )
    except ValidationError as exc:
        messages.error(request, join_validation_error(exc))
    else:
        messages.success(
            request,
            _("Zmieniono operatora w %(n)d rezerwacjach (pominięto %(s)d).")
            % {"n": result["changed_count"], "s": result["skipped_count"]},
        )
    return redirect("reservations:batch_detail", batch_id=batch_id)
