"""Forms for the service app.

* :class:`ServiceRecordForm` — create/edit a single :class:`ServiceRecord`.
* :class:`BulkInspectionForm` — multi-machine inspection form with a single
  shared protokół PDF (uploaded once, attached to every record).
* :class:`ReportFilterForm` — download form on the reports page (year + quarter).
* :class:`ServiceRecordFilterForm` — sidebar filter on the list view.

Tailwind classes are baked into ``widget.attrs`` so templates do not need
``django-widget-tweaks`` for basic rendering — matches the rest of the
project (machines/forms.py, reservations/forms.py).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import FILE_INPUT_CSS, INPUT_CSS, SELECT_CSS, TEXTAREA_CSS
from core.validators import validate_document_upload
from machines.models import Machine

from .models import INSPECTION_INTERVALS, ServiceRecord

# Inspection record types (no naprawa) — used by BulkInspectionForm.
_INSPECTION_TYPE_CHOICES = [
    (value, label)
    for value, label in ServiceRecord.RecordType.choices
    if value in INSPECTION_INTERVALS
]


# =============================================================================
# SERVICE RECORD — single create/edit
# =============================================================================


class ServiceRecordForm(forms.ModelForm):
    """Create / edit form for a single :class:`ServiceRecord`.

    Validation (date < today, auto-update Machine.inspection_date) lives in
    :func:`service.services.create_service_record`; this form only enforces
    field-level constraints. The view calls the service with
    ``form.cleaned_data`` so any :class:`ValidationError` surfaces back to
    the form as a non-field error.
    """

    # Koszt jest modelowo MoneyField (kwota + waluta), ale w formularzu zostaje
    # pojedynczym polem kwoty — waluta to domyślne EUR (ustawiane przez model).
    # Dzięki temu UI nie zyskuje selektora waluty, a warstwa serwisowa zapisuje
    # Decimal, który MoneyField opakowuje w EUR.
    cost = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        label=_("Koszt (EUR)"),
        widget=forms.NumberInput(attrs={"class": INPUT_CSS, "min": "0", "step": "0.01"}),
    )

    class Meta:
        model = ServiceRecord
        fields = [
            "machine",
            "record_type",
            "performed_date",
            "performed_by",
            "description",
            "cost",
            "inspection_document",
        ]
        labels = {
            "machine": _("Maszyna"),
            "record_type": _("Typ wpisu"),
            "performed_date": _("Data wykonania"),
            "performed_by": _("Wykonawca"),
            "description": _("Opis"),
            "inspection_document": _("Protokół (PDF)"),
        }
        widgets = {
            "machine": forms.Select(attrs={"class": SELECT_CSS}),
            "record_type": forms.Select(attrs={"class": SELECT_CSS}),
            "performed_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "class": INPUT_CSS,
                    "data-flatpickr": "true",
                    "data-flatpickr-locale": "pl",
                    "type": "date",
                },
            ),
            "performed_by": forms.TextInput(
                attrs={"class": INPUT_CSS, "placeholder": _("np. Jan Kowalski")}
            ),
            "description": forms.Textarea(attrs={"class": TEXTAREA_CSS, "rows": 3}),
            "inspection_document": forms.ClearableFileInput(
                attrs={"class": FILE_INPUT_CSS, "accept": "application/pdf"}
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Default to a sensible "today" so the input is not blank.
        if not self.is_bound and not self.initial.get("performed_date"):
            self.initial["performed_date"] = date.today()
        # Edycja istniejącego wpisu: pole kwoty pokazuje samą wartość (bez waluty).
        if self.instance and self.instance.pk and self.instance.cost is not None:
            self.initial.setdefault("cost", self.instance.cost.amount)
        # All machines are addable — even in-service / on-site (operator may
        # log post-factum a repair done on a machine that is currently
        # somewhere else). Order by UID for predictable dropdown ordering.
        self.fields["machine"].queryset = Machine.objects.all().order_by("uid")

    def clean_cost(self) -> Decimal:
        cost = self.cleaned_data.get("cost") or Decimal("0.00")
        if cost < 0:
            raise forms.ValidationError(_("Koszt nie może być ujemny."))
        return cost


# =============================================================================
# BULK INSPECTION  (multi-machine + shared PDF)
# =============================================================================


class BulkInspectionForm(forms.Form):
    """Single form to register the same inspection on many machines at once.

    The shared ``inspection_document`` PDF is uploaded once and attached to
    every per-machine :class:`ServiceRecord` created in the same submission
    (see :class:`service.views.BulkInspectionView`).
    """

    machines = forms.ModelMultipleChoiceField(
        queryset=Machine.objects.all().order_by("uid"),
        widget=forms.CheckboxSelectMultiple,
        label=_("Maszyny"),
        help_text=_("Zaznacz wszystkie maszyny objęte tym przeglądem."),
    )
    record_type = forms.ChoiceField(
        choices=_INSPECTION_TYPE_CHOICES,
        label=_("Typ przeglądu"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
    )
    performed_date = forms.DateField(
        label=_("Data przeglądu"),
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "class": INPUT_CSS,
                "data-flatpickr": "true",
                "data-flatpickr-locale": "pl",
                "type": "date",
            },
        ),
    )
    performed_by = forms.CharField(
        required=False,
        max_length=100,
        label=_("Wykonawca"),
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": _("np. Jan Kowalski")}),
    )
    cost = forms.DecimalField(
        required=False,
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
        initial=Decimal("0.00"),
        label=_("Koszt na maszynę (PLN)"),
        widget=forms.NumberInput(attrs={"class": INPUT_CSS, "min": "0", "step": "0.01"}),
    )
    description = forms.CharField(
        required=False,
        label=_("Opis (wspólny)"),
        widget=forms.Textarea(attrs={"class": TEXTAREA_CSS, "rows": 2}),
    )
    inspection_document = forms.FileField(
        required=False,
        label=_("Protokół (PDF, wspólny)"),
        help_text=_("Jeden plik PDF dołączony do każdego utworzonego wpisu."),
        widget=forms.ClearableFileInput(
            attrs={"class": FILE_INPUT_CSS, "accept": "application/pdf"}
        ),
        validators=[validate_document_upload],
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("performed_date"):
            self.initial["performed_date"] = date.today()

    def clean_performed_date(self) -> date:
        performed = self.cleaned_data["performed_date"]
        if performed > date.today():
            raise forms.ValidationError(_("Data przeglądu nie może być w przyszłości."))
        return performed


# =============================================================================
# REPORT FILTER  (download form on /serwis/raporty/)
# =============================================================================


class ReportFilterForm(forms.Form):
    """Form on the reports page — pick year + quarter to download an XLSX."""

    QUARTER_CHOICES = (
        (1, _("Q1 (sty-mar)")),
        (2, _("Q2 (kwi-cze)")),
        (3, _("Q3 (lip-wrz)")),
        (4, _("Q4 (paź-gru)")),
    )

    year = forms.IntegerField(
        min_value=2000,
        max_value=2100,
        initial=date.today().year,
        label=_("Rok"),
        widget=forms.NumberInput(attrs={"class": INPUT_CSS, "min": "2000", "max": "2100"}),
    )
    quarter = forms.ChoiceField(
        choices=QUARTER_CHOICES,
        initial=((date.today().month - 1) // 3) + 1,
        label=_("Kwartał"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
    )


# =============================================================================
# LIST FILTER  (sidebar on /serwis/)
# =============================================================================


class ServiceRecordFilterForm(forms.Form):
    """Sidebar filter form for :class:`service.views.ServiceRecordListView`.

    All fields are optional. The view applies non-empty ``cleaned_data``
    values to the queryset; an unbound or empty form returns "all records".
    """

    TYPE_CHOICES = [("", _("Wszystkie typy")), *ServiceRecord.RecordType.choices]

    record_type = forms.ChoiceField(
        required=False,
        choices=TYPE_CHOICES,
        label=_("Typ"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
    )
    machine = forms.ModelChoiceField(
        required=False,
        queryset=Machine.objects.all().order_by("uid"),
        empty_label=_("Wszystkie maszyny"),
        label=_("Maszyna"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
    )
    performed_after = forms.DateField(
        required=False,
        label=_("Wykonano po"),
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "class": INPUT_CSS,
                "data-flatpickr": "true",
                "data-flatpickr-locale": "pl",
                "type": "date",
            },
        ),
    )
    performed_before = forms.DateField(
        required=False,
        label=_("Wykonano przed"),
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "class": INPUT_CSS,
                "data-flatpickr": "true",
                "data-flatpickr-locale": "pl",
                "type": "date",
            },
        ),
    )
    cost_min = forms.DecimalField(
        required=False,
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
        label=_("Koszt min"),
        widget=forms.NumberInput(attrs={"class": INPUT_CSS, "min": "0", "step": "0.01"}),
    )
    cost_max = forms.DecimalField(
        required=False,
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
        label=_("Koszt max"),
        widget=forms.NumberInput(attrs={"class": INPUT_CSS, "min": "0", "step": "0.01"}),
    )
    expensive_only = forms.BooleanField(
        required=False,
        label=_("Tylko drogie naprawy (powyżej 1000 PLN)"),
        widget=forms.CheckboxInput(
            attrs={
                "class": (
                    "rounded border-gray-300 text-brand-600 focus:ring-brand-500 "
                    "dark:border-gray-600 dark:bg-gray-700 cursor-pointer"
                ),
            }
        ),
    )
    only_inspections = forms.BooleanField(
        required=False,
        label=_("Tylko przeglądy (bez napraw)"),
        widget=forms.CheckboxInput(
            attrs={
                "class": (
                    "rounded border-gray-300 text-brand-600 focus:ring-brand-500 "
                    "dark:border-gray-600 dark:bg-gray-700 cursor-pointer"
                ),
            }
        ),
    )
