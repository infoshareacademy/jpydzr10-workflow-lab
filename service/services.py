"""Business operations for the service app.

All writes to :class:`service.models.ServiceRecord` and the side-effect on
:attr:`machines.Machine.inspection_date` go through this module. Mirrors the
:mod:`reservations.services` style:

* every public function uses keyword-only arguments (the ``*`` after the
  function name) so call sites are self-documenting,
* every write is wrapped in :func:`django.db.transaction.atomic`,
* every public function accepts an optional ``today`` for ``freezegun`` tests,
* business-rule violations raise :class:`django.core.exceptions.ValidationError`
  — views translate them to flash messages.

The "auto-update :attr:`Machine.inspection_date`" behaviour is the *only*
reason this layer exists; without it, an operator would have to manually
keep the per-machine date in sync with the latest performed inspection.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import INSPECTION_INTERVALS, ServiceRecord

logger = logging.getLogger("service")


def recompute_machine_inspection_date(machine) -> None:
    """Przelicz ``Machine.inspection_date`` z POZOSTAŁYCH przeglądów maszyny.

    Ustawia datę na największe ``next_inspection`` wśród rekordów ``przegląd_*``
    danej maszyny, albo ``None`` jeśli żaden przegląd nie istnieje. Wołane po
    usunięciu/edycji wpisu — inaczej maszyna trzymałaby ``inspection_date`` z
    rekordu, którego już nie ma (fałszywe „przegląd aktualny"). ``create`` używa
    monotonicznego bump'a, więc tam recompute nie jest potrzebny.
    """
    from django.db.models import Max

    from machines.models import Machine

    new_date = ServiceRecord.objects.filter(
        machine=machine, record_type__in=INSPECTION_INTERVALS
    ).aggregate(latest=Max("next_inspection"))["latest"]

    locked = Machine.objects.select_for_update().get(pk=machine.pk)
    if locked.inspection_date != new_date:
        locked.inspection_date = new_date
        locked.save(update_fields=["inspection_date", "updated_at"])


def delete_service_record(record: ServiceRecord) -> None:
    """Usuń wpis serwisowy i przelicz ``Machine.inspection_date``.

    Twardy ``DeleteView`` usuwał wiersz bez przeliczenia — maszyna zostawała z
    ``inspection_date`` wskazującą na nieistniejący już przegląd. Tu po usunięciu
    rekomputujemy datę z pozostałych przeglądów (atomowo, pod lockiem maszyny).
    """
    machine_pk = record.machine_id
    with transaction.atomic():
        from machines.models import Machine

        machine = Machine.objects.get(pk=machine_pk)
        record.delete()
        recompute_machine_inspection_date(machine)


# =============================================================================
# CREATE
# =============================================================================


def create_service_record(
    *,
    machine,
    record_type: str,
    performed_date: date,
    performed_by: str = "",
    description: str = "",
    cost: Decimal | float | int = Decimal("0.00"),
    inspection_document=None,
    today: date | None = None,
) -> ServiceRecord:
    """Create a :class:`ServiceRecord` and (for inspections) update the machine.

    Side-effect — when ``record_type`` is one of the ``przegląd_*`` values,
    the helper calculates ``next_inspection = performed_date + N months`` via
    :class:`dateutil.relativedelta.relativedelta` (so February → May is
    exactly three months, not 90 days), then bumps
    :attr:`machines.Machine.inspection_date` if the newly computed date is
    strictly later than the current one. Earlier dates never overwrite the
    machine's stored value — defensive against an operator backdating an
    older inspection by accident.

    Race-condition guard (C1-3 P1): ``select_for_update`` na maszynie chroni
    przed lost-update gdy dwóch techników równolegle wpisuje przegląd dla
    tej samej maszyny — bez locka jeden z bump'ów ``inspection_date``
    zostałby nadpisany przez drugi (klasyczny TOCTOU).

    Raises:
        ValidationError: ``performed_date`` is strictly in the future
            (auditability — we record only completed work).
    """
    today = today or date.today()
    if performed_date > today:
        raise ValidationError({"performed_date": _("Data wykonania nie może być w przyszłości.")})

    next_inspection: date | None = None
    if record_type in INSPECTION_INTERVALS:
        months = INSPECTION_INTERVALS[record_type]
        next_inspection = performed_date + relativedelta(months=months)

    # Import lokalny żeby uniknąć cyklicznego importu (machines.services importuje
    # service.models przez related_name w testach).
    from machines.models import Machine

    with transaction.atomic():
        # Lock maszyny przed read inspection_date — bez tego dwa równoległe
        # create_service_record dla tej samej maszyny mogłyby przeczytać starą
        # inspection_date i bump'nąć ją na różne wartości (lost update).
        machine = Machine.objects.select_for_update().get(pk=machine.pk)

        record = ServiceRecord.objects.create(
            machine=machine,
            record_type=record_type,
            performed_date=performed_date,
            performed_by=performed_by.strip(),
            description=description,
            cost=Decimal(str(cost)),
            inspection_document=inspection_document,
            next_inspection=next_inspection,
        )

        # Bump Machine.inspection_date for przegląd_* (never for naprawa).
        if record.is_inspection and next_inspection is not None:
            current = machine.inspection_date
            if current is None or next_inspection > current:
                machine.inspection_date = next_inspection
                machine.save(update_fields=["inspection_date", "updated_at"])

        logger.info(
            "Wpis serwisowy %s utworzony (maszyna=%s, typ=%s, koszt=%s)",
            record.pk,
            machine.uid,
            record.record_type,
            record.cost,
        )
    return record


# =============================================================================
# UPDATE
# =============================================================================


def update_service_record(record: ServiceRecord, **changes) -> ServiceRecord:
    """Aktualizuje :class:`ServiceRecord` po stworzeniu (poprawa błędnego wpisu).

    Operator wpisuje czasem niewłaściwą datę / koszt / opis. UpdateView w UI
    wywołuje tę funkcję z ``form.cleaned_data`` — pola spoza ``allowed_fields``
    są ignorowane (machine nie wolno migrować — to inny rekord historyczny).

    Jeśli ``performed_date`` lub ``record_type`` się zmieni, zaktualizowane
    zostanie też ``next_inspection`` (recalculate na podstawie aktualnego
    ``record_type``).

    Raises:
        ValidationError: nowa ``performed_date`` jest w przyszłości lub
            ``record_type`` nielegalny.
    """
    allowed_fields = {
        "record_type",
        "performed_date",
        "performed_by",
        "description",
        "cost",
        "inspection_document",
    }
    today = date.today()

    with transaction.atomic():
        locked = ServiceRecord.objects.select_for_update().get(pk=record.pk)

        for field, value in changes.items():
            if field not in allowed_fields:
                continue
            if field == "cost" and value is not None:
                value = Decimal(str(value))
            if field == "performed_by" and isinstance(value, str):
                value = value.strip()
            setattr(locked, field, value)

        if locked.performed_date > today:
            raise ValidationError(
                {"performed_date": _("Data wykonania nie może być w przyszłości.")}
            )

        # Re-calculate next_inspection — uwzględnia nową date + record_type.
        if locked.record_type in INSPECTION_INTERVALS:
            months = INSPECTION_INTERVALS[locked.record_type]
            locked.next_inspection = locked.performed_date + relativedelta(months=months)
        else:
            locked.next_inspection = None

        locked.full_clean()
        locked.save()

        # Edycja daty/typu mogła obniżyć next_inspection — przelicz datę maszyny
        # z prawdziwego maksimum po wszystkich przeglądach (nie zostawiaj stałej).
        recompute_machine_inspection_date(locked.machine)

        logger.info(
            "Wpis serwisowy %s zaktualizowany (maszyna=%s, typ=%s, koszt=%s)",
            locked.pk,
            locked.machine.uid,
            locked.record_type,
            locked.cost,
        )
    return locked


# =============================================================================
# CLOSE SERVICE  (return machine from "W serwisie" to warehouse)
# =============================================================================


def close_service(machine, *, today: date | None = None):
    """Return a machine from ``W serwisie`` to the warehouse.

    Najpierw guard: maszyna MUSI być w stanie ``W serwisie`` (inaczej
    ``ValidationError``) — zapobiega nadpisaniu ``NA_BUDOWIE`` przez „Zakończ
    serwis" na osieroconym wpisie serwisowym (zostawiałoby aktywną rezerwację
    z maszyną fizycznie w magazynie). Po guardzie deleguje do
    ``return_machine_to_warehouse`` (zamyka powiązane rezerwacje + ustawia status
    na ``W magazynie``); ``close_repair`` zwracało tylko Machine, bez zamykania
    rezerwacji.
    """
    from django.core.exceptions import ValidationError

    from machines.models import Machine
    from machines.services import return_machine_to_warehouse

    if machine.status != Machine.Status.W_SERWISIE:
        raise ValidationError(
            _(
                "Nie można zakończyć serwisu — maszyna %(uid)s nie jest "
                "w stanie 'W serwisie' (obecny status: %(status)s)."
            )
            % {"uid": machine.uid, "status": machine.get_status_display()}
        )
    # Po guardzie, deleguj do return_machine_to_warehouse — zamyka rezerwacje
    # plus flip status. close_repair zwraca tylko Machine, NIE zamyka rezerwacji.
    return return_machine_to_warehouse(machine, today=today)
