"""Forms for the machines app.

* :class:`MachineForm` — create/edit a single machine (used by the CRUD views
  and the django-unfold admin overrides).
* :class:`MachineFilterForm` — bound to ``request.GET`` on the list view;
  drives the sidebar filter UI.
* :class:`MachineImportXlsxForm` — single-file upload form for the bulk
  importer.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import FILE_INPUT_CSS, INPUT_CSS, SELECT_CSS, TEXTAREA_CSS

from .models import Machine


class MachineForm(forms.ModelForm):
    """Create/edit form for a single :class:`Machine`."""

    class Meta:
        model = Machine
        fields = [
            "uid",
            "name",
            "machine_type",
            "model",
            "capacity",
            "status",
            "is_reservable",
            "location",
            "inspection_date",
            "manufacturer",
            "serial_number",
            "build_year",
            "notes",
            "image",
        ]
        labels = {
            "uid": _("UID"),
            "name": _("Nazwa"),
            "machine_type": _("Typ"),
            "model": _("Model"),
            "capacity": _("Pojemność"),
            "status": _("Status"),
            "is_reservable": _("Dostępna do rezerwacji"),
            "location": _("Lokalizacja"),
            "inspection_date": _("Data przeglądu"),
            "manufacturer": _("Producent"),
            "serial_number": _("Numer seryjny"),
            "build_year": _("Rok produkcji"),
            "notes": _("Notatki"),
            "image": _("Zdjęcie"),
        }
        widgets = {
            "uid": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": _("np. KOP-001")}),
            "name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "machine_type": forms.Select(attrs={"class": SELECT_CSS}),
            "model": forms.TextInput(attrs={"class": INPUT_CSS}),
            "capacity": forms.NumberInput(attrs={"class": INPUT_CSS, "min": 0}),
            "status": forms.Select(attrs={"class": SELECT_CSS}),
            "is_reservable": forms.CheckboxInput(
                attrs={
                    "class": (
                        "h-4 w-4 rounded border-slate-300 dark:border-slate-600 "
                        "text-brand-600 focus:ring-brand-500"
                    )
                }
            ),
            "location": forms.TextInput(attrs={"class": INPUT_CSS}),
            "inspection_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": INPUT_CSS, "type": "date"},
            ),
            "manufacturer": forms.TextInput(attrs={"class": INPUT_CSS}),
            "serial_number": forms.TextInput(attrs={"class": INPUT_CSS}),
            "build_year": forms.NumberInput(attrs={"class": INPUT_CSS, "min": 0, "max": 2100}),
            "notes": forms.Textarea(attrs={"class": TEXTAREA_CSS, "rows": 3}),
            "image": forms.ClearableFileInput(attrs={"class": FILE_INPUT_CSS, "accept": "image/*"}),
        }


class MachineFilterForm(forms.Form):
    """Filter form for the machine list (bound to ``request.GET``)."""

    INSPECTION_CHOICES = (
        ("", _("Wszystkie")),
        ("ok", _("Przegląd aktualny")),
        ("warning", _("Wkrótce przegląd")),
        ("overdue", _("Przegląd przeterminowany")),
        ("unknown", _("Brak daty przeglądu")),
    )

    search = forms.CharField(
        required=False,
        label=_("Szukaj"),
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": _("UID lub nazwa…")}),
    )
    status = forms.ChoiceField(
        required=False,
        label=_("Status"),
        choices=[("", _("Wszystkie statusy")), *Machine.Status.choices],
        widget=forms.Select(attrs={"class": SELECT_CSS}),
    )
    machine_type = forms.ChoiceField(
        required=False,
        label=_("Typ"),
        choices=[("", _("Wszystkie typy")), *Machine.Type.choices],
        widget=forms.Select(attrs={"class": SELECT_CSS}),
    )
    inspection_status = forms.ChoiceField(
        required=False,
        label=_("Przegląd"),
        choices=INSPECTION_CHOICES,
        widget=forms.Select(attrs={"class": SELECT_CSS}),
    )


# Magic bytes XLSX = nagłówek ZIP (PK\x03\x04). Wszystkie pliki .xlsx są
# w istocie archiwami ZIP — atakujący wgrywający plik z extension .xlsx ale
# zawierający np. shellcode lub HTML byłby teraz złapany przed openpyxl.
_XLSX_MAGIC_BYTES = b"PK\x03\x04"


class MachineImportXlsxForm(forms.Form):
    """Single-file upload form for the bulk machine importer."""

    file = forms.FileField(
        label=_("Plik XLSX"),
        help_text=_("Maksymalnie 5 MB. Wymagane kolumny: uid, name, machine_type."),
        widget=forms.ClearableFileInput(
            attrs={
                "class": FILE_INPUT_CSS,
                "accept": ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        ),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError(_("Plik nie może być większy niż 5 MB."))
        if not upload.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(_("Dozwolone tylko pliki .xlsx."))

        # Magic bytes check — XLSX to ZIP, więc oczekujemy nagłówka 'PK\x03\x04'
        # (C2-4 P0, F9 follow-up). Same extension check łatwo obejść; nieznana
        # zawartość mogłaby crashnąć openpyxl albo wstrzyknąć inny format.
        position = upload.tell() if hasattr(upload, "tell") else 0
        head = upload.read(4)
        if hasattr(upload, "seek"):
            upload.seek(position)
        if not head.startswith(_XLSX_MAGIC_BYTES):
            raise forms.ValidationError(
                _("Plik nie jest poprawnym XLSX (nieprawidłowa sygnatura magic bytes).")
            )

        return upload
