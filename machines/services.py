"""Business operations for the machines app.

Service-layer functions are the *only* place that mutate :class:`Machine`
state. Both Django views and (later) the chatbot tool layer call into these
functions instead of touching the ORM directly, which keeps validation rules
(D6 — no service while reservations exist, status transition matrix) in one
place.

Every public function in this module:

* is wrapped in :func:`django.db.transaction.atomic`,
* accepts an optional ``today`` parameter for ``freezegun`` in tests,
* raises :class:`django.core.exceptions.ValidationError` for business
  violations (never plain ``ValueError`` — views translate ``ValidationError``
  to user-friendly flash messages automatically).
"""

from __future__ import annotations

import logging
from datetime import date

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import Machine

logger = logging.getLogger("machines")


# =============================================================================
# CREATE
# =============================================================================


@transaction.atomic
def create_machine(
    *,
    uid: str,
    name: str,
    machine_type: str = Machine.Type.INNE,
    model: str = "",
    capacity: int = 0,
    inspection_date: date | None = None,
    location: str = "Magazyn",
    status: str = Machine.Status.W_MAGAZYNIE,
    manufacturer: str = "",
    serial_number: str = "",
    build_year: int = 0,
    notes: str = "",
    image=None,
) -> Machine:
    """Create a new :class:`Machine` after running model validation.

    Raises:
        ValidationError: ``uid`` is empty or duplicates an existing record,
            or any field validator fails.
    """
    if not uid or not uid.strip():
        raise ValidationError({"uid": _("UID maszyny nie może być pusty.")})

    machine = Machine(
        uid=uid.strip().upper(),
        name=name.strip(),
        machine_type=machine_type or Machine.Type.INNE,
        model=model.strip(),
        capacity=capacity or 0,
        inspection_date=inspection_date,
        location=location.strip() or "Magazyn",
        status=status,
        manufacturer=manufacturer.strip(),
        serial_number=serial_number.strip(),
        build_year=build_year or 0,
        notes=notes,
    )
    if image is not None:
        machine.image = image

    machine.full_clean()
    machine.save()

    logger.info(
        "Maszyna %s utworzona (typ=%s, status=%s)",
        machine.uid,
        machine.machine_type,
        machine.status,
    )
    return machine


# =============================================================================
# UPDATE
# =============================================================================


def update_machine(machine: Machine, **changes) -> tuple[Machine, list[str]]:
    """Apply partial updates to a :class:`Machine` and re-validate.

    Only fields explicitly present in ``changes`` are touched. Unknown keys
    are ignored (the caller is responsible for the field names — typically a
    Django ``Form.cleaned_data`` dict).

    Returns:
        Tuple ``(machine, warnings)`` — lista ``warnings`` zawiera ostrzeżenia
        biznesowe które operator powinien zobaczyć po zapisaniu zmian, ale
        które NIE są błędami walidacji (W1 P0 #4). Aktualnie:

        * ręczna zmiana statusu na ``Na budowie`` — typowo zmienia się przez
          reservation flow (potwierdzona rezerwacja → daily sync), więc
          bezpośrednia ingerencja sugeruje że magazynier omija logikę
          biznesową (np. dodał maszynę do budowy bez rezerwacji).

    Raises:
        ValidationError: dowolne pole nie przeszło ``full_clean()``.
    """
    warnings: list[str] = []
    allowed_fields = {
        "name",
        "machine_type",
        "model",
        "capacity",
        "inspection_date",
        "location",
        "status",
        "manufacturer",
        "serial_number",
        "build_year",
        "notes",
        "image",
    }

    with transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        original_status = machine.status

        for field, value in changes.items():
            if field not in allowed_fields:
                continue
            setattr(machine, field, value)

        # Detekcja ręcznej zmiany na NA_BUDOWIE — typowy red flag bo magazynier
        # powinien tworzyć rezerwację, nie ustawiać statusu bezpośrednio.
        if (
            original_status != Machine.Status.NA_BUDOWIE
            and machine.status == Machine.Status.NA_BUDOWIE
        ):
            warnings.append(
                _(
                    "Ręczna zmiana statusu na 'Na budowie' — typowo to się dzieje "
                    "automatycznie przez rezerwację. Upewnij się że nie pomijasz "
                    "logiki biznesowej (np. konflikt rezerwacji)."
                )
            )

        machine.full_clean()
        machine.save()
        logger.info("Maszyna %s zaktualizowana (warnings=%d)", machine.uid, len(warnings))

    return machine, warnings


# =============================================================================
# SET TO SERVICE (D6 rule)
# =============================================================================


def _get_future_confirmed_reservations(machine: Machine, today: date):
    """Return future confirmed reservations for ``machine`` or ``None``.

    Uses lazy ``apps.get_model`` lookup so that the machines app can be tested
    without the reservations app being fully wired up (the F2-B agent ships
    the reservations model later). Returns ``None`` if:

    * the model is not yet registered, or
    * the table for it has not been migrated.

    Callers treat the ``None`` return as "no reservations to worry about".
    """
    try:
        reservation_model = apps.get_model("reservations", "Reservation")
    except LookupError:  # pragma: no cover — wymaga app-registry teardown, tylko bootstrap path
        return None

    # The reservations table may exist in code but not in the DB yet (the
    # F2-B agent ships the migration). Probe the schema before issuing a real
    # query — failing the SELECT inside an @atomic block would poison the
    # outer transaction.
    from django.db import connection

    table_name = reservation_model._meta.db_table
    if (
        table_name not in connection.introspection.table_names()
    ):  # pragma: no cover — pre-migration bootstrap
        return None

    confirmed_value = getattr(
        getattr(reservation_model, "Status", None),
        "POTWIERDZONA",
        "potwierdzona",
    )
    return reservation_model.objects.filter(
        machine=machine,
        status=confirmed_value,
        start_date__gte=today,
    ).order_by("start_date")


def set_machine_to_service(machine: Machine, *, today: date | None = None) -> Machine:
    """Move ``machine`` to ``W serwisie``.

    D6 rule (per planning notes): refuse to service a machine that still has
    confirmed reservations in the future — the user must cancel or reschedule
    them first. The exception message includes the number of conflicting
    reservations and the earliest start date so the operator can fix it.

    Also refuses if the machine is currently on a job site (``Na budowie``) —
    it has to be returned to the warehouse first.

    Race-condition guard (C1-2 P1): ``select_for_update`` blokuje równoległe
    transakcje na tym samym rekordzie maszyny — dwóch magazynierów klikających
    'Wyślij do serwisu' równocześnie nie spowoduje już dwóch zapisów (drugi
    czeka, czyta świeży status, widzi że maszyna jest już W_SERWISIE i dostaje
    ValidationError zamiast cichego nadpisania).

    Raises:
        ValidationError: machine is on site, already in service, or has
            future confirmed reservations.
    """
    today = today or date.today()

    with transaction.atomic():
        # select_for_update przed read świeżego statusu — bez tego dwa równoległe
        # POST'y mogłyby przeczytać ten sam status W_MAGAZYNIE i oba zapisać.
        machine = Machine.objects.select_for_update().get(pk=machine.pk)

        if machine.status == Machine.Status.W_SERWISIE:
            raise ValidationError(_("Maszyna %(uid)s jest już w serwisie.") % {"uid": machine.uid})
        if machine.status == Machine.Status.NA_BUDOWIE:
            raise ValidationError(
                _("Maszyna %(uid)s jest na budowie — najpierw zarejestruj zwrot do magazynu.")
                % {"uid": machine.uid}
            )

        future = _get_future_confirmed_reservations(machine, today)
        if future is not None and future.exists():
            count = future.count()
            next_res = future.first()
            raise ValidationError(
                _(
                    "Maszyna %(uid)s ma %(count)d potwierdzonych rezerwacji w przyszłości "
                    "(najbliższa: %(next_start)s). "
                    "Najpierw anuluj lub przenieś rezerwacje."
                )
                % {
                    "uid": machine.uid,
                    "count": count,
                    "next_start": next_res.start_date,
                }
            )

        machine.status = Machine.Status.W_SERWISIE
        machine.save(update_fields=["status", "updated_at"])
        logger.info("Maszyna %s → W serwisie", machine.uid)
    return machine


# =============================================================================
# RETURN TO WAREHOUSE
# =============================================================================


def return_machine_to_warehouse(
    machine: Machine, *, today: date | None = None
) -> dict[str, int | str]:
    """Zwraca maszynę z budowy / serwisu do magazynu i zamyka jej rezerwacje.

    Zmienia status na ``W magazynie`` + lokalizację na ``"Magazyn"``. Dla
    każdej rezerwacji ``POTWIERDZONA`` pokrywającej dzień ``today`` zmienia
    status na ``ZAKONCZONA`` i (jeśli ``end_date`` jest w przyszłości) skraca
    ``end_date`` do ``today`` — to zamyka pętlę między maszyną a jej booking'iem
    (W1 P0 #1: wcześniej operator musiał ręcznie zamykać rezerwacje, co
    powodowało osierocone POTWIERDZONE booking'i).

    Returns:
        Dict ``{"closed": N, "machine_status": str}`` — N to liczba zamkniętych
        rezerwacji, ``machine_status`` to nowy status maszyny (na potrzeby
        flash message w widoku).
    """
    today = today or date.today()
    closed_count = 0

    with transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)

        # Zamknij aktywne rezerwacje (POTWIERDZONA pokrywające dziś) — defensywnie
        # probujemy schemat, bo test może być uruchomiony zanim aplikacja
        # reservations zostanie zmigrowana (analogicznie do
        # ``_get_future_confirmed_reservations``).
        from django.db import connection

        try:
            reservation_model = apps.get_model("reservations", "Reservation")
        except LookupError:  # pragma: no cover — same as above, bootstrap-only
            reservation_model = None

        if (
            reservation_model is not None
            and reservation_model._meta.db_table in connection.introspection.table_names()
        ):
            active_qs = reservation_model.objects.select_for_update().filter(
                machine=machine,
                status=reservation_model.Status.POTWIERDZONA,
                start_date__lte=today,
                end_date__gte=today,
            )
            for reservation in active_qs:
                reservation.status = reservation_model.Status.ZAKONCZONA
                update_fields = ["status", "updated_at"]
                if reservation.end_date > today:
                    reservation.end_date = today
                    update_fields.append("end_date")
                reservation.save(update_fields=update_fields)
                closed_count += 1

        machine.status = Machine.Status.W_MAGAZYNIE
        machine.location = "Magazyn"
        machine.save(update_fields=["status", "location", "updated_at"])
        logger.info(
            "Maszyna %s → W magazynie (zwrot, zamknięto %d rezerwacji)",
            machine.uid,
            closed_count,
        )

    return {"closed": closed_count, "machine_status": machine.status}


# =============================================================================
# CLOSE REPAIR  (service finished — back to warehouse)
# =============================================================================


def close_repair(machine: Machine) -> Machine:
    """Kończy naprawę maszyny — przełącza z ``W serwisie`` na ``W magazynie``.

    Lekka funkcja "zamknij ticket serwisowy" wywoływana przez przycisk
    'Zakończ naprawę' na detail page. Nie zamyka rezerwacji (maszyna w
    serwisie nie ma aktywnych rezerwacji z definicji — patrz D6 rule
    w :func:`set_machine_to_service`), więc nie potrzeba pętli po Reservation.

    W1 P0 #2: wcześniej nie było żadnej ścieżki 'zakończ serwis' — magazynier
    musiał edytować maszynę i ręcznie ustawić status, co psuło audit trail
    (zmiana wyglądała jak ogólny update).

    Raises:
        ValidationError: maszyna nie jest w stanie ``W serwisie``.
    """
    with transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        if machine.status != Machine.Status.W_SERWISIE:
            raise ValidationError(
                _(
                    "Nie można zakończyć naprawy maszyny ze statusem "
                    "'%(status)s' — wymaga 'W serwisie'."
                )
                % {"status": machine.get_status_display()}
            )
        machine.status = Machine.Status.W_MAGAZYNIE
        machine.save(update_fields=["status", "updated_at"])
        logger.info("Maszyna %s — naprawa zakończona (W_SERWISIE → W_MAGAZYNIE)", machine.uid)
    return machine


# =============================================================================
# RETIRE  (machine no longer in fleet)
# =============================================================================


def retire_machine(machine: Machine, *, reason: str = "", today: date | None = None) -> Machine:
    """Trwale wycofuje maszynę z floty — ustawia status ``WYCOFANA``.

    Idempotentne: jeśli maszyna już ma status ``WYCOFANA``, funkcja zwraca
    bieżący obiekt bez modyfikacji. Opcjonalny ``reason`` jest doklejany do
    pola ``notes`` jako wpis ``[WYCOFANA] <reason>`` (pełna ścieżka audytu
    pozostaje w ``simple_history``).

    Wcześniej ta funkcja wymagała statusu ``W serwisie`` i ograniczała się do
    dopisania notatki — to był hack obejścia braku statusu ``WYCOFANA``.
    Teraz mamy właściwy status w ``Machine.Status`` (M2 W1, fix P0 #5), więc
    operator może wycofać maszynę z dowolnego stanu (np. uszkodzona maszyna
    na budowie nie musi wracać przez magazyn).
    """
    with transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        if machine.status == Machine.Status.WYCOFANA:
            # Idempotentne — drugie kliknięcie "Wycofaj" nie zmienia historii.
            return machine
        machine.status = Machine.Status.WYCOFANA
        update_fields = ["status", "updated_at"]
        if reason:
            machine.notes = (machine.notes + f"\n[WYCOFANA] {reason}").strip()
            update_fields.append("notes")
        machine.save(update_fields=update_fields)
        logger.info("Maszyna %s — wycofana z floty (status=WYCOFANA)", machine.uid)
    return machine
