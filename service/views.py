"""Views for the service app.

Class-based views for the CRUD plumbing (less boilerplate), plus a couple of
function-based endpoints for one-off download responses (XLSX / PDF) where a
CBV adds no value.

Layout:

* :class:`ServiceRecordListView` — paginated list with sidebar filters.
* :class:`ServiceRecordDetailView` — single record + "Drukuj PDF" link for
  inspections.
* :class:`ServiceRecordCreateView` — form + file upload.
* :class:`ServiceRecordDeleteView` — POST-only confirm-then-delete.
* :class:`BulkInspectionView` — multi-machine inspection form (calls the
  service inside a single ``@atomic`` block).
* :class:`ReportPageView` — landing page with the report-download form.
* :class:`ReportXlsxView` — streams the kwartalny report as a download.
* :class:`InspectionPdfView` — streams a single PDF protokół for one record.

All write endpoints are wrapped with ``@login_required`` / ``LoginRequiredMixin``
— anonymous traffic gets a redirect to ``accounts:login`` (matches the
project convention).
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)

from core.pagination import PerPageMixin
from core.service_errors import add_form_errors, join_validation_error

from .forms import (
    BulkInspectionForm,
    ReportFilterForm,
    ServiceRecordFilterForm,
    ServiceRecordForm,
)
from .models import ServiceRecord
from .reports import (
    generate_all_service_records_xlsx,
    generate_inspection_pdf,
    generate_machine_service_xlsx,
    generate_quarterly_report_xlsx,
)
from .services import close_service, create_service_record, update_service_record

logger = logging.getLogger("service")

PAGE_SIZE = 20

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# =============================================================================
# LIST + DETAIL
# =============================================================================


class ServiceRecordListView(PerPageMixin, LoginRequiredMixin, ListView):
    """Paginated list of service records with sidebar filters.

    PerPageMixin: ?per_page=N (whitelist 10/20/50/100/500/5000), default 100.
    """

    model = ServiceRecord
    template_name = "service/list.html"
    context_object_name = "records"

    def get_queryset(self):
        qs = ServiceRecord.objects.select_related("machine").order_by("-performed_date", "-pk")
        self.filter_form = ServiceRecordFilterForm(self.request.GET or None)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data.get("record_type"):
                qs = qs.filter(record_type=data["record_type"])
            if data.get("machine"):
                qs = qs.filter(machine=data["machine"])
            if data.get("performed_after"):
                qs = qs.filter(performed_date__gte=data["performed_after"])
            if data.get("performed_before"):
                qs = qs.filter(performed_date__lte=data["performed_before"])
            if data.get("cost_min") is not None:
                qs = qs.filter(cost__gte=data["cost_min"])
            if data.get("cost_max") is not None:
                qs = qs.filter(cost__lte=data["cost_max"])
            if data.get("expensive_only"):
                # F-2: enable expensive() manager (cost > 1000 PLN).
                qs = qs.filter(pk__in=ServiceRecord.objects.expensive().values("pk"))
            if data.get("only_inspections"):
                # F-3: enable inspections() manager (excludes naprawa).
                qs = qs.filter(pk__in=ServiceRecord.objects.inspections().values("pk"))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        ctx["total_count"] = ServiceRecord.objects.count()
        return ctx

    def get_template_names(self):
        # HTMX requests get just the table fragment (used by the filter form
        # ``hx-get`` to live-update results without a full reload).
        if getattr(self.request, "htmx", False):
            return ["service/_record_table.html"]
        return [self.template_name]


class ServiceRecordDetailView(LoginRequiredMixin, DetailView):
    """Detail page for a single service record."""

    model = ServiceRecord
    template_name = "service/detail.html"
    context_object_name = "record"

    def get_queryset(self):
        return ServiceRecord.objects.select_related("machine")


# =============================================================================
# CREATE / DELETE
# =============================================================================


class ServiceRecordCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Create form for a single service record (file upload supported)."""

    model = ServiceRecord
    form_class = ServiceRecordForm
    template_name = "service/form.html"
    permission_required = "service.add_servicerecord"
    raise_exception = True

    def form_valid(self, form):
        try:
            record = create_service_record(
                machine=form.cleaned_data["machine"],
                record_type=form.cleaned_data["record_type"],
                performed_date=form.cleaned_data["performed_date"],
                performed_by=form.cleaned_data.get("performed_by", ""),
                description=form.cleaned_data.get("description", ""),
                cost=form.cleaned_data.get("cost") or Decimal("0.00"),
                inspection_document=form.cleaned_data.get("inspection_document"),
            )
        except ValidationError as exc:
            add_form_errors(form, exc)
            return self.form_invalid(form)

        messages.success(
            self.request, f"Wpis serwisowy {record.pk} dla maszyny {record.machine.uid} dodany."
        )
        return redirect("service:detail", pk=record.pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mode"] = "create"
        return ctx


class ServiceRecordUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Edycja istniejacego wpisu serwisowego (poprawa bledu operatora).

    Reuse ServiceRecordForm — UpdateView automatycznie wypelnia instance.
    Wywoluje update_service_record() ze service'u, ktory walidates
    performed_date <= today i recalculuje next_inspection.
    """

    model = ServiceRecord
    form_class = ServiceRecordForm
    template_name = "service/form.html"
    permission_required = "service.change_servicerecord"
    raise_exception = True

    def form_valid(self, form):
        try:
            record = update_service_record(
                self.object,
                record_type=form.cleaned_data["record_type"],
                performed_date=form.cleaned_data["performed_date"],
                performed_by=form.cleaned_data.get("performed_by", ""),
                description=form.cleaned_data.get("description", ""),
                cost=form.cleaned_data.get("cost") or Decimal("0.00"),
                inspection_document=form.cleaned_data.get("inspection_document"),
            )
        except ValidationError as exc:
            add_form_errors(form, exc)
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Wpis serwisowy #{record.pk} dla maszyny {record.machine.uid} zaktualizowany.",
        )
        return redirect("service:detail", pk=record.pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mode"] = "update"
        ctx["record"] = self.object
        return ctx


class ServiceRecordDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Hard delete — guarded by a confirmation template."""

    model = ServiceRecord
    template_name = "service/delete_confirm.html"
    success_url = reverse_lazy("service:list")
    context_object_name = "record"
    permission_required = "service.delete_servicerecord"
    raise_exception = True

    def form_valid(self, form):
        pk = self.object.pk
        response = super().form_valid(form)
        messages.success(self.request, f"Wpis serwisowy #{pk} usunięty.")
        return response


# =============================================================================
# BULK INSPECTION
# =============================================================================


class BulkInspectionView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    """Multi-machine inspection — one shared protokół PDF, N records created.

    P1 fix (Wave 3 #7): wcześniej każdy zalogowany user mógł bulk-tworzyć
    ServiceRecord (np. obejść per-machine permission gate), bo widok ograniczał
    się do ``LoginRequiredMixin``. Teraz wymaga ``add_servicerecord`` —
    spójne z ``ServiceRecordCreateView``.
    """

    form_class = BulkInspectionForm
    template_name = "service/bulk_inspection.html"
    success_url = reverse_lazy("service:list")
    permission_required = "service.add_servicerecord"
    raise_exception = True

    def form_valid(self, form):
        machines = form.cleaned_data["machines"]
        record_type = form.cleaned_data["record_type"]
        performed_date = form.cleaned_data["performed_date"]
        performed_by = form.cleaned_data.get("performed_by", "") or ""
        description = form.cleaned_data.get("description", "") or ""
        cost = form.cleaned_data.get("cost") or Decimal("0.00")
        upload = form.cleaned_data.get("inspection_document")

        created: list[int] = []
        errors: list[str] = []
        try:
            with transaction.atomic():
                for machine in machines:
                    try:
                        record = create_service_record(
                            machine=machine,
                            record_type=record_type,
                            performed_date=performed_date,
                            performed_by=performed_by,
                            description=description,
                            cost=cost,
                            inspection_document=upload,
                        )
                    except ValidationError as exc:
                        errors.append(f"{machine.uid}: {join_validation_error(exc)}")
                        continue
                    created.append(record.pk)
                    # Rewind the uploaded file so the next iteration can read
                    # the bytes again — matches the bulk_inspection pattern.
                    if upload is not None:
                        upload.seek(0)
                if errors and not created:
                    # All-or-nothing — if every record failed we want the rollback.
                    raise ValidationError(errors)
        except ValidationError as exc:
            for err in getattr(exc, "messages", [str(exc)]):
                form.add_error(None, err)
            return self.form_invalid(form)

        if created:
            messages.success(
                self.request,
                f"Utworzono {len(created)} wpisów przeglądu ({record_type}).",
            )
        for err in errors[:10]:
            messages.warning(self.request, err)
        if len(errors) > 10:
            messages.warning(self.request, f"...oraz {len(errors) - 10} dalszych błędów.")
        return super().form_valid(form)


# =============================================================================
# REPORTS
# =============================================================================


class ReportPageView(LoginRequiredMixin, TemplateView):
    """Landing page for reports — form to pick year + quarter."""

    template_name = "service/reports.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = ReportFilterForm(self.request.GET or None)
        return ctx


class ReportXlsxView(LoginRequiredMixin, View):
    """Stream the kwartalny report as a single XLSX attachment."""

    def get(self, request: HttpRequest, year: int, quarter: int) -> HttpResponse:
        try:
            payload = generate_quarterly_report_xlsx(year=year, quarter=quarter)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("service:reports")

        filename = slugify(f"raport-q{quarter}-{year}") + ".xlsx"
        response = HttpResponse(payload, content_type=XLSX_CONTENT_TYPE)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class MachineServiceXlsxView(LoginRequiredMixin, View):
    """Stream historię serwisu pojedynczej maszyny jako XLSX attachment.

    URL: ``/serwis/eksport/maszyna/<uid>/`` — pobierany z karty maszyny
    (machines/detail.html → tab "Historia serwisu" → button "Pobierz Excel").
    """

    def get(self, request: HttpRequest, uid: str) -> HttpResponse:
        from machines.models import Machine

        machine = get_object_or_404(Machine, uid=uid)
        payload = generate_machine_service_xlsx(machine=machine)
        filename = slugify(f"serwis-{machine.uid}-{date.today().isoformat()}") + ".xlsx"
        response = HttpResponse(payload, content_type=XLSX_CONTENT_TYPE)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class AllServiceRecordsXlsxView(LoginRequiredMixin, View):
    """Stream pełną historię serwisu (wszystkie maszyny) jako XLSX attachment.

    URL: ``/serwis/eksport/wszystkie/`` — pobierany z listy serwisów
    (service/list.html → button "Pobierz Excel — wszystkie wpisy").
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        payload = generate_all_service_records_xlsx()
        filename = slugify(f"serwis-wszystkie-{date.today().isoformat()}") + ".xlsx"
        response = HttpResponse(payload, content_type=XLSX_CONTENT_TYPE)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class InspectionPdfView(LoginRequiredMixin, View):
    """Stream a single PDF protokół for one :class:`ServiceRecord`."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        record = get_object_or_404(ServiceRecord.objects.select_related("machine"), pk=pk)
        payload = generate_inspection_pdf(service_record=record)
        filename = slugify(f"protokol-srv-{record.pk:06d}-{date.today().isoformat()}") + ".pdf"
        response = HttpResponse(payload, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# =============================================================================
# CLOSE SERVICE  (return machine from "W serwisie" back to warehouse)
# =============================================================================


@login_required
@require_POST
@permission_required("machines.change_machine", raise_exception=True)
def close_service_view(request: HttpRequest, pk: int) -> HttpResponse:
    """End an active repair — flip the machine status back to ``W magazynie``.

    Wrapper na :func:`service.services.close_service` (delegujące do
    :func:`machines.services.return_machine_to_warehouse`). Wymaga POST +
    perm ``machines.change_machine`` — bo realnie zmieniamy stan maszyny,
    nie wpisu serwisowego. Service-level guard rzuca ``ValidationError``
    gdy maszyna nie jest ``W serwisie`` (np. ktoś podwójnie kliknął) i
    przepuszczamy ten komunikat jako flash error.
    """
    record = get_object_or_404(ServiceRecord.objects.select_related("machine"), pk=pk)
    try:
        close_service(record.machine)
    except ValidationError as exc:
        for message in getattr(exc, "messages", [str(exc)]):
            messages.error(request, message)
    else:
        messages.success(
            request,
            _("Serwis zakończony — maszyna %(uid)s wraca do magazynu.")
            % {"uid": record.machine.uid},
        )
    return redirect("service:detail", pk=pk)
