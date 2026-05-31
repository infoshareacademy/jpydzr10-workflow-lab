"""Forms for the reservations app.

* :class:`ReservationForm` — CRUD form for :class:`Reservation`. Hooks
  Flatpickr to the date fields via ``data-flatpickr`` so the date picker
  renders in PL locale (see ``templates/base.html`` for the init script).
* :class:`ReservationFilterForm` — sidebar filter on the list view.
* :class:`ConstructionSiteForm` — CRUD form for :class:`ConstructionSite`.

All visible labels and help texts are Polish (ZASADA #2). Tailwind classes
are baked into ``widget.attrs`` so templates do not need
``django-widget-tweaks`` for the basic form rendering — it is still loaded
project-wide for the few places that want ad-hoc tweaks.
"""

from __future__ import annotations

from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import INPUT_CSS, SELECT_CSS, TEXTAREA_CSS
from machines.models import Machine

from .models import ConstructionSite, Reservation
from .services import MIN_OPERATOR_NAME_LENGTH

# =============================================================================
# RESERVATION
# =============================================================================


class ReservationForm(forms.ModelForm):
    """Create / edit form for a :class:`Reservation`.

    Validation (date order, conflict check) lives in the service layer; this
    form only enforces field-level constraints. The view calls
    :func:`reservations.services.create_reservation` /
    :func:`reservations.services.update_reservation` with
    ``form.cleaned_data`` so any :class:`ValidationError` raised in the
    service surfaces back through the form as a non-field error.
    """

    class Meta:
        model = Reservation
        fields = [
            "machine",
            "site",
            "start_date",
            "end_date",
            "person",
            "responsible_person",
            "address",
            "notes",
        ]
        labels = {
            "machine": _("Maszyna"),
            "site": _("Budowa"),
            "start_date": _("Data początku"),
            "end_date": _("Data końca"),
            "person": _("Osoba rezerwująca"),
            "responsible_person": _("Osoba odpowiedzialna na budowie"),
            "address": _("Adres dostawy"),
            "notes": _("Notatki"),
        }
        widgets = {
            "machine": forms.Select(attrs={"class": SELECT_CSS}),
            "site": forms.Select(attrs={"class": SELECT_CSS}),
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "class": INPUT_CSS,
                    "data-flatpickr": "true",
                    "data-flatpickr-locale": "pl",
                    "type": "date",
                },
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "class": INPUT_CSS,
                    "data-flatpickr": "true",
                    "data-flatpickr-locale": "pl",
                    "type": "date",
                },
            ),
            "person": forms.TextInput(
                attrs={"class": INPUT_CSS, "placeholder": _("Imię i nazwisko")}
            ),
            "responsible_person": forms.TextInput(
                attrs={
                    "class": INPUT_CSS,
                    "placeholder": _("Imię i nazwisko kierownika / brygadzisty"),
                }
            ),
            "address": forms.TextInput(
                attrs={"class": INPUT_CSS, "placeholder": _("Adres dostawy (ulica, miasto)")}
            ),
            "notes": forms.Textarea(attrs={"class": TEXTAREA_CSS, "rows": 3}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Filter the machine dropdown to "reservable" machines only — but if
        # we are editing an existing reservation, keep its machine even if it
        # has since gone to service (so the form does not show "this field
        # is required" after a status flip).
        # Wave 4 P0 fix: WYCOFANA też wykluczamy z dropdownu, bo maszyna
        # wycofana z floty (sprzedana / złomowana) nie może być rezerwowana —
        # wcześniej UI pozwalał wybrać taką maszynę i tworzyć rezerwacje na
        # już-nieistniejący sprzęt (regression z dodania statusu WYCOFANA).
        reservable = Machine.objects.exclude(
            status__in=[Machine.Status.W_SERWISIE, Machine.Status.WYCOFANA]
        ).filter(is_reservable=True)
        if self.instance and self.instance.pk and self.instance.machine_id:
            reservable = reservable | Machine.objects.filter(pk=self.instance.machine_id)
        self.fields["machine"].queryset = reservable.distinct().order_by("uid")
        self.fields["site"].queryset = ConstructionSite.objects.filter(
            status=ConstructionSite.Status.AKTYWNA
        ).order_by("project_number")
        self.fields["site"].empty_label = _("— bez budowy —")
        # Wave 14-A Bundle 4 -- Sebastian walkthrough: address + responsible_person
        # wymagane na poziomie form (model zostaje blank=True dla backwards-compat
        # z M1 fixtures). help_text wyjasniajacy rozdzielnosc `person` (biuro)
        # vs `responsible_person` (budowa).
        self.fields["address"].required = True
        self.fields["address"].help_text = _(
            "Adres budowy/dostawy maszyny. Wymagane — pojawi sie w PDF wydruku."
        )
        self.fields["responsible_person"].required = True
        self.fields["responsible_person"].help_text = _(
            "Imie i nazwisko kierownika/brygadzisty odpowiedzialnego za maszyne na budowie."
        )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("Data końca musi być >= data początku."))
        # Wave 14-A Bundle 4 -- explicit non-empty strip (default field validator
        # przepuszcza " " jako valid). Bez tego user moglby wpisac " " (spacja)
        # i ominac required check.
        address = cleaned.get("address")
        if address is not None and not address.strip():
            self.add_error("address", _("Adres dostawy jest wymagany."))
        responsible = cleaned.get("responsible_person")
        if responsible is not None and not responsible.strip():
            self.add_error(
                "responsible_person",
                _("Imie i nazwisko osoby odpowiedzialnej na budowie jest wymagane."),
            )
        return cleaned


# =============================================================================
# RESERVATION FILTERS  (list-view sidebar)
# =============================================================================


class ReservationFilterForm(forms.Form):
    """Sidebar filter form for :class:`reservations.views.ReservationListView`.

    All fields are optional. The view applies non-empty ``cleaned_data``
    values to the queryset; an unbound or fully-empty form returns "all
    reservations".
    """

    STATUS_CHOICES = [("", _("Wszystkie statusy")), *Reservation.Status.choices]

    q = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": _("Osoba, notatki, budowa..."),
                "aria-label": _("Globalne wyszukiwanie rezerwacji"),
            }
        ),
        label=_("Szukaj"),
        help_text=_("Przeszukuje osobę, adres, notatki oraz nazwę/numer budowy."),
    )
    status = forms.ChoiceField(
        required=False,
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={"class": SELECT_CSS}),
        label=_("Status"),
    )
    machine = forms.ModelChoiceField(
        required=False,
        queryset=Machine.objects.all().order_by("uid"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
        empty_label=_("Wszystkie maszyny"),
        label=_("Maszyna"),
    )
    site = forms.ModelChoiceField(
        required=False,
        queryset=ConstructionSite.objects.all().order_by("-created_at"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
        empty_label=_("Wszystkie budowy"),
        label=_("Budowa"),
    )
    person = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": _("Szukaj po osobie")}),
        label=_("Osoba"),
    )
    start_after = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "class": INPUT_CSS,
                "data-flatpickr": "true",
                "data-flatpickr-locale": "pl",
                "type": "date",
            },
        ),
        label=_("Początek po"),
    )
    end_before = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "class": INPUT_CSS,
                "data-flatpickr": "true",
                "data-flatpickr-locale": "pl",
                "type": "date",
            },
        ),
        label=_("Koniec przed"),
    )


# =============================================================================
# CONSTRUCTION SITE
# =============================================================================


class ConstructionSiteForm(forms.ModelForm):
    """Create / edit form for a :class:`ConstructionSite`.

    ``project_number`` is editable on create and *read-only on edit* — once a
    project is registered its number is a stable business identifier (it may
    appear on PDFs / external systems). The view passes ``editable=False``
    via the constructor when editing.
    """

    class Meta:
        model = ConstructionSite
        fields = [
            "project_number",
            "name",
            "client_name",
            "address",
            "city",
            "status",
            "start_date",
            "end_date",
            "notes",
        ]
        labels = {
            "project_number": _("Numer projektu"),
            "name": _("Nazwa budowy"),
            "client_name": _("Klient"),
            "address": _("Adres"),
            "city": _("Miasto"),
            "status": _("Status"),
            "start_date": _("Data rozpoczęcia"),
            "end_date": _("Planowana data zakończenia"),
            "notes": _("Notatki"),
        }
        widgets = {
            "project_number": forms.TextInput(
                attrs={
                    "class": INPUT_CSS,
                    "placeholder": f"10{date.today().year % 100:02d}00000001",
                }
            ),
            "name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "client_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "address": forms.TextInput(attrs={"class": INPUT_CSS}),
            "city": forms.TextInput(attrs={"class": INPUT_CSS}),
            "status": forms.Select(attrs={"class": SELECT_CSS}),
            "start_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "class": INPUT_CSS,
                    "data-flatpickr": "true",
                    "data-flatpickr-locale": "pl",
                    "type": "date",
                },
            ),
            "end_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "class": INPUT_CSS,
                    "data-flatpickr": "true",
                    "data-flatpickr-locale": "pl",
                    "type": "date",
                },
            ),
            "notes": forms.Textarea(attrs={"class": TEXTAREA_CSS, "rows": 3}),
        }

    def __init__(self, *args, editable_project_number: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not editable_project_number:
            self.fields["project_number"].disabled = True
            self.fields["project_number"].help_text = _(
                "Numer projektu nie podlega edycji po utworzeniu budowy."
            )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error(
                "end_date", _("Planowana data zakończenia musi być >= data rozpoczęcia.")
            )
        return cleaned


# =============================================================================
# B-4 — CHANGE OPERATOR (modal "Zmień osobę")
# =============================================================================


class ChangeOperatorForm(forms.Form):
    """Modal form do zmiany osoby przypisanej do rezerwacji (B-4).

    Walidacje "biznesowe" (rezerwacja zamknięta, identyczne imię) zostają w
    serwisie ``change_operator`` — tu odsiewamy tylko pustki i za-krótkie
    wartości żeby nie wysyłać round-trip do bazy.
    """

    new_person = forms.CharField(
        max_length=100,
        min_length=3,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": _("np. Sven Olsen"),
                "autocomplete": "off",
                "x-model": "newPerson",
            }
        ),
        label=_("Nowa osoba"),
        help_text=_("Imię i nazwisko nowego operatora (min. 3 znaki)."),
    )

    def clean_new_person(self) -> str:
        return (self.cleaned_data.get("new_person") or "").strip()


# =============================================================================
# B-6 — SWAP MACHINE (modal "Wymień maszynę")
# =============================================================================


class SwapMachineForm(forms.Form):
    """Modal form do wymiany maszyny mid-reservation (B-6).

    Queryset ``new_machine`` wyklucza obecną maszynę rezerwacji + maszyny
    ``WYCOFANA`` (terminalny stan) i ``W_SERWISIE`` (już niedostępne). Pole
    ``reason`` jest opcjonalne — trafia do notatek obu rezerwacji (audit).
    """

    new_machine = forms.ModelChoiceField(
        queryset=Machine.objects.none(),
        widget=forms.Select(attrs={"class": SELECT_CSS, "x-model": "newMachine"}),
        label=_("Maszyna zastępcza"),
        empty_label=_("— wybierz maszynę zastępczą —"),
        help_text=_("Maszyna, która przejmie rezerwację od dziś do końca okresu."),
    )
    reason = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "class": TEXTAREA_CSS,
                "rows": 3,
                "placeholder": _("np. Awaria silnika KOP-001, klient wymaga ciągłej pracy"),
                "x-model": "reason",
            }
        ),
        label=_("Powód wymiany"),
        help_text=_("Opcjonalny — trafia do notatek obu rezerwacji (audit)."),
    )

    def __init__(self, *args, current_machine_id: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Wyklucz obecną maszynę + WYCOFANA + W_SERWISIE. Magazyn / NA_BUDOWIE /
        # ZAREZERWOWANA są dopuszczalne — service ``swap_machine`` przeleci
        # przez ``has_conflict`` w pozostałym okresie.
        excluded_statuses = [Machine.Status.WYCOFANA, Machine.Status.W_SERWISIE]
        qs = Machine.objects.exclude(status__in=excluded_statuses)
        if current_machine_id is not None:
            qs = qs.exclude(pk=current_machine_id)
        self.fields["new_machine"].queryset = qs.order_by("uid")


# =============================================================================
# B-7 — BATCH RESERVATION (multi-maszynowa rezerwacja)
# =============================================================================


class BatchReservationForm(forms.Form):
    """B-7 — formularz tworzenia grupy rezerwacji (multi-machine).

    Magazynier wybiera N maszyn (checkbox multi-select) + wpisuje wspólne
    pola raz (osoba / budowa / daty / adres / notatki) → submit tworzy N
    rezerwacji jednym kliknięciem, wszystkie z tym samym ``batch_id``.

    Walidacja form-level (te 4 reguły): non-empty machines, end >= start,
    person min 3 znaki, datetime sanity. Walidacja biznesowa (konflikty,
    status maszyny, limit 50) jest w :func:`services.create_batch_reservation`
    — błędy z service'a są surfaced przez ``add_form_errors``.
    """

    machines = forms.ModelMultipleChoiceField(
        queryset=Machine.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={"class": "batch-machines-grid"}),
        label=_("Maszyny"),
        help_text=_(
            "Zaznacz wszystkie maszyny dla tej grupy rezerwacji "
            "(każda dostanie osobny wpis z tym samym ID grupy)."
        ),
    )
    site = forms.ModelChoiceField(
        queryset=ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA).order_by(
            "project_number"
        ),
        required=False,
        empty_label=_("— bez budowy —"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
        label=_("Budowa"),
        help_text=_("Opcjonalna — wspólna budowa dla wszystkich rezerwacji w grupie."),
    )
    start_date = forms.DateField(
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "class": INPUT_CSS,
                "data-flatpickr": "true",
                "data-flatpickr-locale": "pl",
                "type": "date",
            },
        ),
        label=_("Data początku"),
    )
    end_date = forms.DateField(
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "class": INPUT_CSS,
                "data-flatpickr": "true",
                "data-flatpickr-locale": "pl",
                "type": "date",
            },
        ),
        label=_("Data końca"),
    )
    person = forms.CharField(
        max_length=100,
        min_length=MIN_OPERATOR_NAME_LENGTH,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": _("Imię i nazwisko kierownika / operatora"),
                "autocomplete": "off",
            }
        ),
        label=_("Osoba rezerwująca"),
        help_text=_("Wspólna osoba odpowiedzialna za wszystkie maszyny w grupie."),
    )
    address = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": _("Adres dostawy (opcjonalnie)"),
            }
        ),
        label=_("Adres dostawy"),
        help_text=_("Opcjonalny — jeśli wszystkie maszyny mają być dostarczone na ten sam adres."),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": TEXTAREA_CSS, "rows": 3}),
        label=_("Notatki"),
        help_text=_("Opcjonalne — wspólne notatki kopiowane do każdej rezerwacji w grupie."),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Queryset machines liczymy lazy w ``__init__`` (nie w field default)
        # bo ``Machine`` API nie jest dostępne na import-time (circular safety).
        # WYCOFANA + W_SERWISIE wykluczone — service powtórzy guard, ale UX
        # benefit: użytkownik nie widzi maszyn których i tak nie wybierze.
        self.fields["machines"].queryset = Machine.objects.exclude(
            status__in=[Machine.Status.WYCOFANA, Machine.Status.W_SERWISIE]
        ).order_by("uid")

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("Data końca musi być >= data początku."))
        person = cleaned.get("person")
        if person:
            cleaned["person"] = person.strip()
        return cleaned


# =============================================================================
# B-7 — BULK ACTIONS na batch detail page
# =============================================================================


class BatchCancelForm(forms.Form):
    """Form do bulk-anulowania wszystkich rezerwacji w grupie batch.

    Reason (z :class:`Reservation.CancellationReason`) jest wymagany dla
    całej grupy — wszystkie anulowane rezerwacje dostają ten sam reason,
    co ułatwia agregację w raportach miesięcznych (B-2).
    """

    cancellation_reason = forms.ChoiceField(
        choices=[("", _("— wybierz powód —")), *Reservation.CancellationReason.choices],
        widget=forms.Select(attrs={"class": SELECT_CSS}),
        label=_("Powód anulowania"),
        help_text=_("Wspólny powód dla wszystkich rezerwacji w grupie."),
    )
    cancellation_note = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "class": TEXTAREA_CSS,
                "rows": 2,
                "placeholder": _("Dodatkowy kontekst (opcjonalnie)"),
            }
        ),
        label=_("Notatka"),
    )


class BatchChangeOperatorForm(forms.Form):
    """Form do bulk-zmiany operatora wszystkich rezerwacji w grupie batch."""

    new_person = forms.CharField(
        max_length=100,
        min_length=MIN_OPERATOR_NAME_LENGTH,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": _("np. Sven Olsen"),
                "autocomplete": "off",
            }
        ),
        label=_("Nowa osoba"),
        help_text=_(
            "Imię i nazwisko nowego operatora — zostanie zaktualizowane na wszystkich aktywnych rezerwacjach."
        ),
    )

    def clean_new_person(self) -> str:
        return (self.cleaned_data.get("new_person") or "").strip()
