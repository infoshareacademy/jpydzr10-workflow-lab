"""Współdzielona warstwa filtrowania wpisów serwisowych.

Jedno źródło prawdy dla WSZYSTKICH ośmiu filtrów listy serwisowej — używane
zarówno przez widok listy, eksport XLSX, jak i endpoint danych do wykresu.
Dzięki temu tabela, plik Excel i wykres zawsze pokazują DOKŁADNIE ten sam
zestaw rekordów dla danego querystringa.
"""

from __future__ import annotations

from django.db.models import QuerySet

from .forms import ServiceRecordFilterForm
from .models import ServiceRecord


def filter_service_records(params, base_qs: QuerySet | None = None) -> QuerySet:
    """Zwraca wpisy serwisowe przefiltrowane wg parametrów (np. ``request.GET``).

    Walidacja i koercja typów odbywa się przez :class:`ServiceRecordFilterForm`
    (te same reguły co w widoku listy). Przy niepoprawnych parametrach zwracany
    jest niezfiltrowany ``base_qs`` (spójnie z dotychczasowym zachowaniem listy).

    Sortowanie NIE jest tu nakładane — należy do wołającego (widok listy trzyma
    własny ``order_by``).
    """
    if base_qs is None:
        base_qs = ServiceRecord.objects.select_related("machine")

    form = ServiceRecordFilterForm(params or None)
    if not form.is_valid():
        return base_qs

    data = form.cleaned_data
    qs = base_qs
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
        qs = qs.filter(pk__in=ServiceRecord.objects.expensive().values("pk"))
    if data.get("only_inspections"):
        qs = qs.filter(pk__in=ServiceRecord.objects.inspections().values("pk"))
    return qs
