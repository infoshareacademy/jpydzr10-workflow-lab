"""Business operations for the reservations app.

The service layer is the *only* place that mutates :class:`Reservation` /
:class:`ConstructionSite` state. Views (and later the chatbot tool layer)
call these functions instead of touching the ORM directly so that:

* validation rules (date order, conflict detection, status transitions)
  live in exactly one place,
* every write happens inside ``@transaction.atomic`` so partial state never
  reaches the database,
* :func:`run_daily_sync` can be invoked from both a management command (cron)
  and the admin without code duplication.

Every public function:

* takes keyword-only arguments (the ``*`` after the function name) so the
  call sites are self-documenting,
* accepts an optional ``today`` parameter for ``freezegun`` in tests,
* raises :class:`django.core.exceptions.ValidationError` for business
  violations (views translate it to flash messages automatically).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import TYPE_CHECKING

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import ConstructionSite, Reservation

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

    from machines.models import Machine

logger = logging.getLogger("reservations")

# Minimalna długość imienia/nazwiska operatora — odrzucamy single-char żeby
# uniknąć przypadkowych literówek ("X") oraz pustych stringów po stripie.
MIN_OPERATOR_NAME_LENGTH = 3

# B-7: maksymalna liczba maszyn w jednej grupie batch — limit chroni przed
# nieumyślnym DoS (np. user zaznaczył "wszystko" w queryset 200+ rekordów).
# Powyżej tego progu zmuszamy do podziału na mniejsze grupy.
MAX_BATCH_MACHINES = 50


# =============================================================================
# STATE MACHINE  —  legalne przejścia statusów rezerwacji
# =============================================================================

# KEY = obecny status, VALUE = zbiór legalnych "next" statusów.
# Każda zmiana statusu w services MUSI przejść przez ten matrix
# (wywołanie ``_assert_legal_transition`` przed mutacją ``reservation.status``).
# Dwa stany terminalne (ZAKONCZONA, ANULOWANA) mają pusty zbiór — nie można
# ich cofnąć ani przejść dalej (no resurrection of historical bookings).
RESERVATION_TRANSITIONS: dict[str, set[str]] = {
    Reservation.Status.OCZEKUJACA: {
        Reservation.Status.POTWIERDZONA,
        Reservation.Status.ANULOWANA,
    },
    Reservation.Status.POTWIERDZONA: {
        Reservation.Status.ZAKONCZONA,
        Reservation.Status.ANULOWANA,
    },
    Reservation.Status.ZAKONCZONA: set(),  # terminalny — nie można cofnąć
    Reservation.Status.ANULOWANA: set(),  # terminalny
}


def _assert_legal_transition(current: str, target: str) -> None:
    """Raise :class:`ValidationError` jeśli przejście statusu jest nielegalne.

    Args:
        current: Aktualny ``reservation.status``.
        target: Docelowy status z ``Reservation.Status``.

    Raises:
        ValidationError: gdy ``target`` nie jest w
            :data:`RESERVATION_TRANSITIONS[current]` (np. próba cofnięcia
            zakończonej rezerwacji, "skoku" OCZEKUJACA → ZAKONCZONA, itp.).
    """
    if target not in RESERVATION_TRANSITIONS.get(current, set()):
        raise ValidationError(
            _("Nielegalne przejście statusu rezerwacji: %(current)s → %(target)s")
            % {"current": current, "target": target}
        )


# =============================================================================
# CONFLICT DETECTION
# =============================================================================


def has_conflict(
    *,
    machine_id: int,
    start: date,
    end: date,
    exclude_pk: int | None = None,
) -> bool:
    """Return ``True`` when ``machine_id`` is already booked in ``[start, end]``.

    Touching dates (``end_a == start_b``) are treated as a conflict — in the
    construction-equipment business a machine needs at least one day for
    transport / preparation between bookings (M1 rule, kept for M2).

    Cancelled / completed reservations are ignored (they belong to history
    and do not affect future availability).

    Args:
        machine_id: PK of the :class:`machines.Machine`.
        start: First day of the candidate booking.
        end: Last day of the candidate booking.
        exclude_pk: Optional reservation PK to exclude (used when editing
            an existing reservation so it does not "conflict with itself").

    Raises:
        ValidationError: ``end < start``.
    """
    if end < start:
        raise ValidationError(_("Data końca musi być >= data początku."))

    return Reservation.objects.conflicts_for(
        machine_id=machine_id, start=start, end=end, exclude_pk=exclude_pk
    ).exists()


def get_conflicting_reservations(
    *,
    machine_id: int,
    start: date,
    end: date,
    exclude_pk: int | None = None,
) -> list[Reservation]:
    """Return the list of conflicting reservations (for UI display).

    Returns up to all conflicting rows — the caller typically slices to the
    first 3 for the warning message. Uses ``select_related`` so the template
    can render machine / site names without N+1 queries.
    """
    qs = Reservation.objects.conflicts_for(
        machine_id=machine_id, start=start, end=end, exclude_pk=exclude_pk
    ).select_related("machine", "site")
    return list(qs)


# =============================================================================
# CREATE / UPDATE / TRANSITIONS
# =============================================================================


@transaction.atomic
def create_reservation(
    *,
    machine_id: int,
    site_id: int | None,
    start_date: date,
    end_date: date,
    person: str,
    address: str = "",
    notes: str = "",
    responsible_person: str = "",
    today: date | None = None,
    require_full_fields: bool = False,
    created_by=None,
) -> Reservation:
    """Create a new :class:`Reservation` after running all validations.

    A row-level lock is acquired on the machine via ``select_for_update`` so
    two concurrent requests cannot both pass the conflict check and create
    overlapping reservations (classic check-then-act race).

    Args:
        require_full_fields: Wave 14-H Bundle M-1 — gdy ``True``, wymusza
            niepuste ``responsible_person`` (>=3 znaki) oraz ``address``
            (>=5 znaków). Ustawiamy ``True`` na wywołania z form'a (UI) i
            chatbota. Default ``False`` zachowuje wsteczną kompatybilność
            dla historycznych testów i migracji M1 fixtures bez tych pól.

    Raises:
        ValidationError: any of: empty ``person``, ``end_date < start_date``,
            ``end_date`` in the past, machine has a conflicting reservation,
            ``machine_id`` does not exist. Plus (gdy ``require_full_fields``):
            empty ``responsible_person`` lub ``address``.
    """
    today = today or date.today()

    if not person or not person.strip():
        raise ValidationError({"person": _("Pole 'osoba rezerwująca' nie może być puste.")})
    # Wave 14-H Bundle M-1: defense-in-depth pól form'a — chatbot i przyszłe
    # API nie mogą tworzyć rezerwacji "ad-hoc" bez kierownika i adresu.
    if require_full_fields:
        if not responsible_person or len(responsible_person.strip()) < 3:
            raise ValidationError({"responsible_person": _("Osoba odpowiedzialna jest wymagana.")})
        if not address or len(address.strip()) < 5:
            raise ValidationError({"address": _("Adres dostawy jest wymagany.")})
    if end_date < start_date:
        raise ValidationError({"end_date": _("Data końca musi być >= data początku.")})
    if end_date < today:
        raise ValidationError({"end_date": _("Nie można tworzyć rezerwacji w przeszłości.")})

    # Lock the machine row so a concurrent create_reservation() blocks until
    # this transaction commits — prevents the conflict-check race condition.
    Machine = apps.get_model("machines", "Machine")
    try:
        machine = Machine.objects.select_for_update().get(pk=machine_id)
    except Machine.DoesNotExist as exc:
        raise ValidationError({"machine": _("Wskazana maszyna nie istnieje.")}) from exc

    # Wave 4 P0 fix: maszyna wycofana z floty (status=WYCOFANA) nie może być
    # rezerwowana — to terminalny stan (sprzedana / złomowana). Forma już
    # ją wyklucza z dropdownu, ale defence-in-depth: blokujemy też w service
    # layer (bezpośrednie wywołanie z admin / chatbot tool / API).
    if machine.status == Machine.Status.WYCOFANA:
        raise ValidationError(
            {
                "machine": _(
                    "Maszyna %(uid)s została wycofana z floty "
                    "— nie można tworzyć dla niej nowych rezerwacji."
                )
                % {"uid": machine.uid}
            }
        )

    # Maszyny magazynowe (np. wózki widłowe obsługujące magazyn) zostają w
    # bazie i są widoczne na timeline (śledzimy przegląd), ale nie można ich
    # rezerwować na budowę. Form wyklucza je z dropdownu — to defence-in-depth
    # dla wywołań z chatbota / admin / API.
    if not machine.is_reservable:
        raise ValidationError(
            {
                "machine": _(
                    "Maszyna %(uid)s jest oznaczona jako magazynowa "
                    "— nie można jej rezerwować na budowę."
                )
                % {"uid": machine.uid}
            }
        )

    # Walidacja budowy: nie mozna rezerwowac maszyny na zakonczona / anulowana
    # budowe. Sytuacja "36 aktywnych rezerwacji na zakonczonej budowie" pokazuje
    # ze logika nigdy nie blokowala dodawania nowych rezerwacji do nieaktywnej
    # budowy.
    if site_id is not None:
        try:
            target_site = ConstructionSite.objects.get(pk=site_id)
        except ConstructionSite.DoesNotExist as exc:
            raise ValidationError({"site": _("Wskazana budowa nie istnieje.")}) from exc
        if target_site.status != ConstructionSite.Status.AKTYWNA:
            raise ValidationError(
                {
                    "site": _(
                        "Budowa %(project_number)s ma status %(status)s "
                        "— nie można na niej tworzyć nowych rezerwacji."
                    )
                    % {
                        "project_number": target_site.project_number,
                        "status": target_site.get_status_display(),
                    }
                }
            )

    if has_conflict(machine_id=machine_id, start=start_date, end=end_date):
        conflicts = get_conflicting_reservations(
            machine_id=machine_id, start=start_date, end=end_date
        )
        details = "; ".join(f"{r.start_date} - {r.end_date}" for r in conflicts[:3])
        raise ValidationError(
            _("Maszyna %(uid)s ma %(count)d kolidujących rezerwacji w tym terminie: %(details)s")
            % {"uid": machine.uid, "count": len(conflicts), "details": details}
        )

    reservation = Reservation.objects.create(
        machine=machine,
        site_id=site_id,
        start_date=start_date,
        end_date=end_date,
        person=person.strip(),
        address=address.strip(),
        notes=notes,
        responsible_person=(responsible_person or "").strip(),
        status=Reservation.Status.OCZEKUJACA,
        created_by=created_by,
    )
    logger.info(
        "Rezerwacja %s utworzona (%s %s - %s)",
        reservation.pk,
        machine.uid,
        start_date,
        end_date,
    )
    return reservation


@transaction.atomic
def update_reservation(
    reservation: Reservation,
    *,
    today: date | None = None,
    **fields,
) -> Reservation:
    """Apply partial updates to ``reservation`` and re-validate.

    If ``start_date`` or ``end_date`` changes, re-runs :func:`has_conflict`
    excluding the reservation itself so it does not conflict with its own
    current dates.

    Allowed fields: ``start_date``, ``end_date``, ``person``, ``address``,
    ``notes``, ``site_id``. Unknown keys are ignored. ``status`` is NOT
    settable here — use the dedicated ``confirm_/cancel_/complete_`` helpers.

    Hard Return Policy: status ``ZAKONCZONA`` w szczególności jest blokowany
    explicit (zamiast tylko silently-ignored), żeby zatrzymać próby obejścia
    :func:`complete_reservation` — która odpowiednio zwraca maszynę do magazynu
    przez :func:`machines.services.return_machine_to_warehouse`. Bezpośredni
    setattr status=ZAKONCZONA pozostawiłby maszynę w stanie ``Na budowie``.
    """
    # Hard Return Policy guard — explicit refusal, nie cichą ignorancją.
    if "status" in fields and fields["status"] == Reservation.Status.ZAKONCZONA:
        raise ValidationError(
            _(
                "Nie można ustawić statusu ZAKONCZONA bezpośrednio. "
                "Użyj complete_reservation() — zwraca też maszynę do magazynu."
            )
        )

    # Terminal state guard — zakonczone i anulowane rezerwacje sa terminalne,
    # NIE da sie ich edytowac. Bez tego guard'a user moglby edytowac
    # zakonczona rezerwacje (np. skrocic end_date) co tworzy mylacy
    # audit trail (history pokazuje 'edycja zwrocila maszyne' chociaz
    # maszyna byla juz zwrocona przy complete).
    if reservation.status in {Reservation.Status.ZAKONCZONA, Reservation.Status.ANULOWANA}:
        raise ValidationError(
            _(
                "Nie można edytować rezerwacji o statusie %(status)s — jest terminalna. "
                "Aby zmienić dane, utwórz nową rezerwację."
            )
            % {"status": reservation.get_status_display()}
        )

    allowed = {
        "start_date",
        "end_date",
        "person",
        "address",
        "notes",
        "site_id",
        # Wave 14-A Bundle 4 -- responsible_person editable via update_reservation
        "responsible_person",
    }

    new_start = fields.get("start_date", reservation.start_date)
    new_end = fields.get("end_date", reservation.end_date)
    if new_end < new_start:
        raise ValidationError({"end_date": _("Data końca musi być >= data początku.")})
    dates_changed = (new_start, new_end) != (reservation.start_date, reservation.end_date)
    if dates_changed and has_conflict(
        machine_id=reservation.machine_id,
        start=new_start,
        end=new_end,
        exclude_pk=reservation.pk,
    ):
        raise ValidationError(_("Nowy termin koliduje z inną rezerwacją tej maszyny."))

    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in {"person", "address", "responsible_person"} and isinstance(value, str):
            value = value.strip()
        setattr(reservation, key, value)

    reservation.save()
    logger.info("Rezerwacja %s zaktualizowana", reservation.pk)
    return reservation


@transaction.atomic
def confirm_reservation(reservation: Reservation, *, today: date | None = None) -> Reservation:
    """Move a reservation to ``potwierdzona``.

    Re-fetches the row under ``select_for_update`` so concurrent confirms on
    the same PK serialise through this transaction — eliminates the classic
    "two managers approve the same booking simultaneously" race. Also
    re-runs :func:`has_conflict` pod lockiem (race-safe approval): w
    międzyczasie inny manager mógł potwierdzić nakładającą się rezerwację
    dla tej samej maszyny, więc trzeba przeliczyć konflikt.

    Legal transitions: ``OCZEKUJACA → POTWIERDZONA`` (see
    :data:`RESERVATION_TRANSITIONS`).

    Raises:
        ValidationError: nielegalne przejście statusu lub wykryto konflikt
            pod lockiem (race condition catch).
    """
    locked = Reservation.objects.select_for_update().get(pk=reservation.pk)
    _assert_legal_transition(locked.status, Reservation.Status.POTWIERDZONA)

    # Recheck conflicts pod lockiem — sprawdza inne POTWIERDZONA/OCZEKUJACA
    # rezerwacje na tej samej maszynie w tym samym oknie czasowym (z wykluczeniem
    # własnego PK, aby się nie kolidować "z samym sobą").
    if has_conflict(
        machine_id=locked.machine_id,
        start=locked.start_date,
        end=locked.end_date,
        exclude_pk=locked.pk,
    ):
        # Pokazujemy uzytkownikowi LISTE konfliktujacych rezerwacji zeby
        # wiedzial gdzie konkretnie jest nakladanie — bez tego user widzi
        # tylko "konflikt" i myli sie ze go nie ma (timeline wizualnie
        # nakladajace bary moga byc zakryte przez inny bar wyzej w stacku).
        conflicts = list(
            get_conflicting_reservations(
                machine_id=locked.machine_id,
                start=locked.start_date,
                end=locked.end_date,
                exclude_pk=locked.pk,
            )
        )
        details = "; ".join(
            f"#{c.pk} {c.start_date}→{c.end_date} ({c.get_status_display()}, {c.person})"
            for c in conflicts[:3]
        )
        raise ValidationError(
            _(
                "Nie można potwierdzić — rezerwacja #%(pk)s (%(start)s→%(end)s) "
                "nakłada się z %(count)d innymi rezerwacjami: %(details)s"
            )
            % {
                "pk": locked.pk,
                "start": locked.start_date,
                "end": locked.end_date,
                "count": len(conflicts),
                "details": details,
            }
        )

    locked.status = Reservation.Status.POTWIERDZONA
    locked.save(update_fields=["status", "updated_at"])
    logger.info("Rezerwacja %s → potwierdzona", locked.pk)
    return locked


@transaction.atomic
def cancel_reservation(
    reservation: Reservation,
    *,
    reason: str = "",
    note: str = "",
    today: date | None = None,
) -> Reservation:
    """Cancel a non-terminal reservation z wymaganym powodem (B-2).

    Idempotent: cancelling an already-cancelled reservation is a no-op
    (returns the locked row). Re-fetches under ``select_for_update`` to
    serialise z równoległym confirm/complete na tym samym PK.

    Legal transitions: ``OCZEKUJACA → ANULOWANA``, ``POTWIERDZONA → ANULOWANA``.
    Próba anulowania zakończonej rezerwacji rzuca :class:`ValidationError`
    via :func:`_assert_legal_transition`.

    B-2 — pole ``reason`` jest wymagane gdy aktualnie anulujemy (nie-idempotent
    path). Walidujemy że ``reason`` jest jedną z wartości
    :class:`Reservation.CancellationReason`. ``note`` jest opcjonalna
    (dodatkowy kontekst). Wymóg dotyczy WSZYSTKICH ścieżek wywołania
    (admin bulk action też musi podać reason).
    """
    locked = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if locked.status == Reservation.Status.ANULOWANA:
        return locked  # idempotent — bez wymagania reason

    _assert_legal_transition(locked.status, Reservation.Status.ANULOWANA)

    # B-2: reason wymagany — wszystkie nowe anulowania muszą mieć powód.
    valid_reasons = {choice for choice, _label in Reservation.CancellationReason.choices}
    if not reason:
        raise ValidationError({"cancellation_reason": _("Powód anulowania jest wymagany.")})
    if reason not in valid_reasons:
        raise ValidationError(
            {"cancellation_reason": _("Nieznany powód anulowania: %(reason)s") % {"reason": reason}}
        )

    locked.status = Reservation.Status.ANULOWANA
    locked.cancellation_reason = reason
    locked.cancellation_note = (note or "").strip()
    locked.save(
        update_fields=[
            "status",
            "cancellation_reason",
            "cancellation_note",
            "updated_at",
        ]
    )
    logger.info("Rezerwacja %s → anulowana (powód=%s)", locked.pk, reason)
    return locked


@transaction.atomic
def complete_reservation(
    reservation: Reservation,
    *,
    actual_return_date: date | None = None,
    today: date | None = None,
) -> Reservation:
    """Mark a confirmed reservation as ``zakończona`` and return the machine.

    Only confirmed reservations can be completed — completing a pending
    booking has no business meaning (it was never approved). Re-fetches
    pod ``select_for_update`` so a concurrent cancel/complete na tym samym
    PK serialises through this transaction. The machine is sent back to
    the warehouse via :func:`machines.services.return_machine_to_warehouse`.

    Legal transitions: ``POTWIERDZONA → ZAKONCZONA``.

    B-3 — opcjonalny parametr ``actual_return_date`` (jeśli klient zwraca
    wcześniej). Walidacje:
      * actual_return_date >= start_date (nie można zwrócić przed startem),
      * actual_return_date <= today (przyszłe zwroty nie mają sensu).
    Jeśli ``None`` (default), zachowujemy istniejące zachowanie — pole
    pozostaje NULL i konflikty/raporty używają ``end_date``.
    """
    today = today or date.today()
    locked = Reservation.objects.select_for_update().get(pk=reservation.pk)
    _assert_legal_transition(locked.status, Reservation.Status.ZAKONCZONA)

    # Walidacja Bug 19 (Sebastian incydent #256 — Minikoparka 4 zaakceptowana
    # ze start_date=04.06 i zakonczona 31.05; maszyna nigdy nie pojechala na
    # budowe). Zakonczenie = zwrot maszyny do magazynu. Niemozliwe gdy start
    # jeszcze nie nadszedl — maszyna nie wyjechala wiec nie ma czego zwrocic.
    # Wlasciwa akcja w tym scenariuszu to ANULUJ rezerwacje (cancel_reservation),
    # nie complete. Wprowadzamy ValidationError z jasnym wskazaniem alternatywy.
    if locked.start_date > today:
        raise ValidationError(
            _(
                "Nie można zakończyć rezerwacji #%(pk)s — start (%(start)s) "
                "jeszcze nie nadszedł, maszyna nie wyjechała na budowę. "
                "Użyj 'Anuluj rezerwację' jeśli chcesz cofnąć wynajem."
            )
            % {"pk": locked.pk, "start": locked.start_date}
        )

    update_fields = ["status", "updated_at"]
    if actual_return_date is not None:
        if actual_return_date < locked.start_date:
            raise ValidationError(
                {
                    "actual_return_date": _(
                        "Faktyczna data zwrotu nie może być wcześniejsza niż data początku rezerwacji."
                    )
                }
            )
        if actual_return_date > today:
            raise ValidationError(
                {"actual_return_date": _("Faktyczna data zwrotu nie może być w przyszłości.")}
            )
        locked.actual_return_date = actual_return_date
        update_fields.append("actual_return_date")

    locked.status = Reservation.Status.ZAKONCZONA
    locked.save(update_fields=update_fields)

    # Lazy import — avoids a circular import at module load time and keeps
    # the reservations app independently importable for unit tests.
    from machines.services import return_machine_to_warehouse

    return_machine_to_warehouse(locked.machine, today=today)
    logger.info("Rezerwacja %s → zakończona, maszyna %s zwrócona", locked.pk, locked.machine.uid)
    return locked


# =============================================================================
# DAILY SYNC  —  Hard Return Policy
# =============================================================================


@transaction.atomic
def run_daily_sync(*, today: date | None = None) -> dict[str, int | date]:
    """Daily reconciliation of machine status against confirmed reservations.

    Rules, in priority order:

    1. Machines whose status is ``W serwisie`` are skipped (service overrides
       automation — a broken machine stays broken until a manual fix).
    2. A confirmed reservation whose period covers today (``start ≤ today
       ≤ end``) flips the machine to ``Na budowie`` and copies the address
       (preferring ``reservation.address`` over ``reservation.site.address``,
       falling back to the existing ``machine.location``).
    3. A confirmed reservation that has already ended (``end < today``)
       while the machine is still ``Na budowie`` extends its ``end_date``
       to today — the **Hard Return Policy**: the machine has not been
       physically returned yet, so the booking is conservatively kept open.
    4. After the per-reservation pass, any ``W magazynie`` machine that has
       a confirmed future booking is flipped to ``Zarezerwowana`` — the
       second pass guarantees the result is independent of iteration order
       (a fix vs. the M1 single-pass implementation that was order-dependent).

    Returns:
        Dict with the keys ``updated``, ``extended``, ``reserved``,
        ``today`` (for telemetry / management-command output).
    """
    today = today or date.today()
    Machine = apps.get_model("machines", "Machine")

    updated = extended = reserved = released = 0

    confirmed = (
        Reservation.objects.filter(status=Reservation.Status.POTWIERDZONA)
        .select_related("machine", "site")
        .order_by("start_date")
    )

    # ------------------------------------------------------------------
    # Pass 1 — per-reservation status updates + Hard Return Policy extends.
    # ------------------------------------------------------------------
    for res in confirmed:
        machine = res.machine
        if machine.status == Machine.Status.W_SERWISIE:
            continue

        start, end = res.start_date, res.end_date

        if start <= today <= end:
            # Active reservation — make sure the machine reflects it.
            if machine.status != Machine.Status.NA_BUDOWIE:
                machine.status = Machine.Status.NA_BUDOWIE
                machine.location = res.address or (
                    res.site.address if res.site else machine.location
                )
                machine.save(update_fields=["status", "location", "updated_at"])
                updated += 1
        elif end < today and machine.status == Machine.Status.NA_BUDOWIE:
            # Hard Return Policy — extend the booking instead of "ending" it.
            res.end_date = today
            res.save(update_fields=["end_date", "updated_at"])
            extended += 1

    # ------------------------------------------------------------------
    # Pass 2 — warehouse machines with a confirmed future booking become
    # ``Zarezerwowana``. Separated from Pass 1 so the result is independent
    # of the iteration order of the confirmed queryset.
    # ------------------------------------------------------------------
    for res in confirmed:
        if res.start_date <= today:
            continue
        machine = res.machine
        if machine.status == Machine.Status.W_MAGAZYNIE:
            machine.status = Machine.Status.ZAREZERWOWANA
            machine.save(update_fields=["status", "updated_at"])
            reserved += 1

    # ------------------------------------------------------------------
    # Pass 3 — release stale statuses. NA_BUDOWIE/ZAREZERWOWANA without
    # corresponding confirmed reservation (active or future) reverts to
    # W_MAGAZYNIE. Handles cases where reservations were cancelled,
    # completed, or edited bypassing the normal status flow (manual admin
    # changes, swap_machine, batch operations).
    # ------------------------------------------------------------------
    stale_qs = Machine.objects.filter(
        status__in=[Machine.Status.NA_BUDOWIE, Machine.Status.ZAREZERWOWANA]
    )
    for machine in stale_qs:
        active = Reservation.objects.filter(
            machine=machine,
            status=Reservation.Status.POTWIERDZONA,
            start_date__lte=today,
            end_date__gte=today,
        ).exists()
        if active:
            # NA_BUDOWIE correct; nothing to do (Pass 1 handled flips into it).
            continue

        has_future = Reservation.objects.filter(
            machine=machine,
            status=Reservation.Status.POTWIERDZONA,
            start_date__gt=today,
        ).exists()

        target = Machine.Status.ZAREZERWOWANA if has_future else Machine.Status.W_MAGAZYNIE
        if machine.status != target:
            machine.status = target
            machine.save(update_fields=["status", "updated_at"])
            released += 1

    logger.info(
        "Daily sync (%s): updated=%d, extended=%d, reserved=%d, released=%d",
        today,
        updated,
        extended,
        reserved,
        released,
    )
    return {
        "updated": updated,
        "extended": extended,
        "reserved": reserved,
        "released": released,
        "today": today,
    }


# =============================================================================
# CONSTRUCTION SITES
# =============================================================================


@transaction.atomic
def create_site(
    *,
    project_number: str,
    name: str,
    address: str,
    client_name: str = "",
    city: str = "",
    status: str = ConstructionSite.Status.AKTYWNA,
    start_date: date | None = None,
    end_date: date | None = None,
    notes: str = "",
) -> ConstructionSite:
    """Create a new :class:`ConstructionSite` after running model validation.

    The ``project_number`` validator (``BUD-RRRR-NNN``) and ``end_date >=
    start_date`` cross-field check run via :meth:`full_clean`.
    """
    site = ConstructionSite(
        project_number=project_number.strip(),
        name=name.strip(),
        client_name=client_name.strip(),
        address=address.strip(),
        city=city.strip(),
        status=status,
        start_date=start_date,
        end_date=end_date,
        notes=notes,
    )
    site.full_clean()
    site.save()
    logger.info("Budowa %s utworzona", site.project_number)
    return site


@transaction.atomic
def update_site(site: ConstructionSite, **fields) -> ConstructionSite:
    """Apply partial updates to ``site`` and re-validate.

    Allowed fields mirror the form: ``name``, ``client_name``, ``address``,
    ``city``, ``status``, ``start_date``, ``end_date``, ``notes``. Unknown
    keys are ignored. ``project_number`` is intentionally read-only after
    creation — it is a stable business identifier.
    """
    allowed = {
        "name",
        "client_name",
        "address",
        "city",
        "status",
        "start_date",
        "end_date",
        "notes",
    }
    for key, value in fields.items():
        if key not in allowed:
            continue
        if isinstance(value, str):
            value = value.strip() if key not in {"notes"} else value
        setattr(site, key, value)

    site.full_clean()
    site.save()
    logger.info("Budowa %s zaktualizowana", site.project_number)
    return site


@transaction.atomic
def delete_site(site: ConstructionSite) -> None:
    """Delete ``site`` after refusing if it still has open reservations.

    Closed (``anulowana``/``zakończona``) reservations are fine — they will
    be orphaned via ``on_delete=PROTECT`` only if they are still ``aktywne``.
    Sebastian explicitly does NOT want a cascade here.
    """
    if site.has_active_reservations:
        raise ValidationError(
            _("Nie można usunąć budowy %(project_number)s: posiada %(count)d aktywnych rezerwacji.")
            % {
                "project_number": site.project_number,
                "count": site.active_reservation_count,
            }
        )
    project_number = site.project_number
    site.delete()
    logger.info("Budowa %s usunięta", project_number)


# =============================================================================
# BREAKDOWN  —  one-click flow "Zgłoś awarię" (B-1)
# =============================================================================


@transaction.atomic
def report_breakdown(
    reservation: Reservation,
    *,
    description: str,
    actor: AbstractBaseUser | None = None,
    today: date | None = None,
) -> dict[str, int | str]:
    """One-click awaria flow — magazynierka klika 1 przycisk i:

    1. Zamyka rezerwację dniem dzisiejszym (``status=ZAKONCZONA``,
       ``end_date=today`` jeśli wcześniej była w przyszłości).
    2. Maszyna → ``W_SERWISIE`` (bezpośredni setattr — D6 guard pominięty
       celowo, bo zamykamy aktywną rezerwację w tej samej transakcji,
       więc warunek "future reservations" już nie obowiązuje).
    3. Tworzy :class:`service.models.ServiceRecord` typu ``naprawa`` z
       opisem awarii (audit trail kto i kiedy zgłosił).

    Cały flow w jednej transakcji — jeśli krok 3 padnie, rezerwacja i
    maszyna wracają do poprzedniego stanu (atomic).

    Args:
        reservation: Otwarta rezerwacja (``OCZEKUJACA`` lub ``POTWIERDZONA``).
        description: Wymagany opis awarii (min 5 znaków po stripie).
        actor: Użytkownik zgłaszający — używany jako ``performed_by`` w
            :class:`ServiceRecord` (string z ``get_full_name`` lub ``username``).
        today: Opcjonalna data — ``freezegun`` w testach.

    Returns:
        ``{"reservation_id": int, "machine_uid": str,
        "service_record_id": int}`` — używane przez view do flash message.

    Raises:
        ValidationError: rezerwacja zamknięta lub opis za krótki.
    """
    from machines.models import Machine
    from service.models import ServiceRecord
    from service.services import create_service_record

    today = today or date.today()

    description = (description or "").strip()
    if len(description) < 5:
        raise ValidationError({"description": _("Opis awarii musi mieć co najmniej 5 znaków.")})

    # Lock rezerwacji ZANIM cokolwiek odczytamy — chroni przed równoległym
    # cancel/complete/breakdown na tym samym PK.
    locked = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if locked.is_closed:
        raise ValidationError(
            _("Nie można zgłosić awarii dla zamkniętej rezerwacji (status=%(status)s).")
            % {"status": locked.get_status_display()}
        )

    # 1. Zamknij rezerwację — bezpośredni setattr (omijamy
    #    _assert_legal_transition bo OCZEKUJACA → ZAKONCZONA byłaby
    #    nielegalna w standardowym flow; awaria jest specjalnym shortcut
    #    "z każdego otwartego stanu → ZAKONCZONA dziś").
    if locked.end_date > today:
        locked.end_date = today
    locked.status = Reservation.Status.ZAKONCZONA
    locked.save(update_fields=["status", "end_date", "updated_at"])

    # 2. Maszyna → W_SERWISIE. Lock maszyny (select_for_update) chroni przed
    #    równoległą zmianą jej statusu. Pomijamy ``set_machine_to_service``
    #    bo:
    #      a) ono samo robi select_for_update — double lock nie zaszkodzi,
    #         ale daje to dwie sub-tx i utrudnia diagnostykę,
    #      b) jego D6 guard sprawdza FUTURE potwierdzone rezerwacje, ale
    #         tu właśnie zamknęliśmy aktywną — chcemy "wymuszone" przejście.
    machine_locked = Machine.objects.select_for_update().get(pk=locked.machine_id)
    machine_locked.status = Machine.Status.W_SERWISIE
    machine_locked.save(update_fields=["status", "updated_at"])

    # 3. ServiceRecord typu "naprawa". performed_by to display name
    #    użytkownika (string) — historia audytu, kto zgłosił.
    performer_label = ""
    if actor is not None:
        performer_label = actor.get_full_name() or actor.get_username()
    record = create_service_record(
        machine=machine_locked,
        record_type=ServiceRecord.RecordType.NAPRAWA,
        performed_date=today,
        performed_by=performer_label,
        description=f"Awaria mid-reservation (#{locked.pk}): {description}",
        today=today,
    )

    logger.info(
        "Awaria zgłoszona dla rezerwacji %s — maszyna %s w serwisie, ServiceRecord %s utworzony.",
        locked.pk,
        machine_locked.uid,
        record.pk,
    )
    return {
        "reservation_id": locked.pk,
        "machine_uid": machine_locked.uid,
        "service_record_id": record.pk,
    }


# =============================================================================
# CHANGE OPERATOR  —  mid-reservation (B-4)
# =============================================================================


@transaction.atomic
def change_operator(
    reservation: Reservation,
    *,
    new_person: str,
    actor: AbstractBaseUser | None = None,
) -> Reservation:
    """Zmienia osobę przypisaną do rezerwacji bez tworzenia nowej (B-4).

    Use case biznesowy: Tomek bierze KOP-001 na pn-pt, we wtorek rano dzwoni
    "L4, Sven przejmie". Rezerwacja zostaje (ta sama maszyna, daty, budowa,
    status, notatki) ALE ``person`` zostaje zaktualizowane na "Sven Olsen".

    Audit trail jest zachowany przez ``django-simple-history`` —
    ``HistoricalReservation`` przy każdym ``save()`` snapshotuje wszystkie
    pola, w tym ``person`` przed zmianą. Detail page renderuje listę zmian
    via ``reservation.history.all``.

    Args:
        reservation: Aktywna rezerwacja (``OCZEKUJACA`` lub ``POTWIERDZONA``).
        new_person: Nowe imię i nazwisko operatora — wymagane, min 3 znaki
            po stripie, musi się różnić od obecnego.
        actor: Użytkownik wykonujący zmianę (loguje się tylko username).

    Returns:
        Zaktualizowana rezerwacja (refreshed z DB pod ``select_for_update``).

    Raises:
        ValidationError: rezerwacja zamknięta, ``new_person`` pusty/za krótki,
            ``new_person`` identyczne z obecnym (case-insensitive po stripie).
    """
    locked = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if locked.is_closed:
        raise ValidationError(
            _("Nie można zmienić osoby dla zamkniętej rezerwacji (status=%(status)s).")
            % {"status": locked.get_status_display()}
        )

    new_person = (new_person or "").strip()
    if not new_person:
        raise ValidationError({"new_person": _("Nowa osoba jest wymagana.")})
    if len(new_person) < MIN_OPERATOR_NAME_LENGTH:
        raise ValidationError(
            {
                "new_person": _("Imię i nazwisko musi mieć co najmniej %(n)d znaki.")
                % {"n": MIN_OPERATOR_NAME_LENGTH}
            }
        )

    # Case-insensitive compare po stripie — "Sven Olsen" == "  sven olsen  ".
    # Plan M3: gdy ``person`` zostanie FK do EmployeeProfile, porównujemy PK.
    if new_person.casefold() == locked.person.strip().casefold():
        raise ValidationError({"new_person": _("Nowa osoba musi się różnić od obecnej.")})

    previous_person = locked.person
    logger.info(
        "Rezerwacja %s: zmiana operatora '%s' → '%s' (actor=%s)",
        locked.pk,
        previous_person,
        new_person,
        actor.get_username() if actor is not None else "system",
    )
    locked.person = new_person
    # _history_user — django-simple-history hook na FK history_user, dzięki
    # czemu w detail.html "Historia zmian" pokaże kto wykonał zmianę.
    if actor is not None:
        locked._history_user = actor  # type: ignore[attr-defined]
    locked.save(update_fields=["person", "updated_at"])
    return locked


# =============================================================================
# SWAP MACHINE  —  mid-reservation (B-6)
# =============================================================================


@transaction.atomic
def swap_machine(
    reservation: Reservation,
    *,
    new_machine: Machine,
    reason: str = "",
    actor: AbstractBaseUser | None = None,
    today: date | None = None,
) -> dict[str, int | str]:
    """Wymiana maszyny mid-reservation (B-6) — kończy starą rezerwację dzisiaj
    i tworzy nową na zastępczą maszynę pokrywającą pozostały okres.

    Use case: KOP-001 psuje się w dniu 3 z 5-dniowej rezerwacji. Magazynierka
    klika "Wymień maszynę" → wybiera KOP-002 → submit. Konsekwencje:

      * **Rezerwacja oryginalna** (KOP-001):
          - ``end_date`` = ``today`` (jeśli wcześniej była w przyszłości),
          - ``status`` = ``ZAKONCZONA``,
          - ``notes`` += banner "[Wymieniona na KOP-002 dnia YYYY-MM-DD]: powód",
          - ``replaced_by`` = FK do nowej rezerwacji.
      * **Nowa rezerwacja** (KOP-002):
          - ``start_date`` = ``today``,
          - ``end_date`` = oryginalny ``end_date``,
          - ``person`` / ``site`` / ``address`` skopiowane,
          - ``status`` = ``POTWIERDZONA`` (zakładamy że wymiana jest aktywna),
          - ``notes`` zawiera odwołanie do oryginalnej rezerwacji.
      * **Maszyna oryginalna** (KOP-001): próba przesunięcia do ``W_SERWISIE``
        — jeśli się nie powiedzie (np. ma inne future rezerwacje), zostaje
        bez zmian z ``logger.warning`` (best-effort, nie blokuje swap'a).

    Args:
        reservation: Aktywna rezerwacja (``OCZEKUJACA`` lub ``POTWIERDZONA``).
        new_machine: Maszyna zastępcza (≠ obecna, nie ``WYCOFANA``).
        reason: Opcjonalny powód wymiany (trafia do notatek obu rezerwacji).
        actor: Użytkownik wykonujący wymianę (audit przez simple-history).
        today: Opcjonalna data — ``freezegun`` w testach.

    Returns:
        ``{"original_id": int, "new_id": int, "machine_to_service_uid": str
        | None}`` — ostatnie pole = ``None`` gdy nie udało się przenieść
        maszyny do serwisu (np. ma inne rezerwacje).

    Raises:
        ValidationError: rezerwacja zamknięta, ``new_machine`` identyczne
            z obecnym, ``new_machine`` wycofane, ``new_machine`` ma konflikt
            rezerwacji w pozostałym okresie ``[today, end_date]``.
    """
    today = today or date.today()
    machine_model = apps.get_model("machines", "Machine")

    locked = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if locked.is_closed:
        raise ValidationError(
            _("Nie można wymienić maszyny dla zamkniętej rezerwacji (status=%(status)s).")
            % {"status": locked.get_status_display()}
        )
    if new_machine.pk == locked.machine_id:
        raise ValidationError({"new_machine": _("Maszyna zastępcza musi się różnić od obecnej.")})
    if new_machine.status == machine_model.Status.WYCOFANA:
        raise ValidationError(
            {
                "new_machine": _(
                    "Maszyna %(uid)s została wycofana z floty — nie może być zastępcą."
                )
                % {"uid": new_machine.uid}
            }
        )
    if not new_machine.is_reservable:
        raise ValidationError(
            {
                "new_machine": _(
                    "Maszyna %(uid)s jest oznaczona jako magazynowa "
                    "— nie może być zastępcą na budowie."
                )
                % {"uid": new_machine.uid}
            }
        )

    # Wave 11 M-3 fix: lockujemy OBIE maszyny w jednym query ORDER BY pk
    # (deterministyczna kolejność locków → brak deadlock'a przy 2 parallel
    # swap operations swapujących te same 2 maszyny w przeciwnych kierunkach).
    pks_sorted = sorted([new_machine.pk, locked.machine_id])
    locked_machines = list(
        machine_model.objects.select_for_update().filter(pk__in=pks_sorted).order_by("pk")
    )
    machines_by_pk = {m.pk: m for m in locked_machines}
    new_machine_locked = machines_by_pk[new_machine.pk]

    # Pozostały okres = [today, locked.end_date]. Jeśli locked.end_date < today
    # (np. overdue Hard Return), traktujemy "od dziś do dziś" — minimum 1 dzień.
    remaining_start = today
    remaining_end = max(locked.end_date, today)

    if has_conflict(
        machine_id=new_machine_locked.pk,
        start=remaining_start,
        end=remaining_end,
    ):
        conflicts = get_conflicting_reservations(
            machine_id=new_machine_locked.pk,
            start=remaining_start,
            end=remaining_end,
        )
        details = "; ".join(f"{r.start_date} - {r.end_date}" for r in conflicts[:3])
        raise ValidationError(
            _(
                "Maszyna zastępcza %(uid)s ma %(count)d kolidujących rezerwacji "
                "w okresie %(start)s — %(end)s: %(details)s"
            )
            % {
                "uid": new_machine_locked.uid,
                "count": len(conflicts),
                "start": remaining_start,
                "end": remaining_end,
                "details": details,
            }
        )

    # 1. Utwórz nową rezerwację PIERWSZE — bo `replaced_by` na locked
    #    wymaga PK nowej. Status POTWIERDZONA bo wymiana jest aktywna —
    #    klient już pracuje, nie ma sensu przechodzić przez OCZEKUJACA.
    reason_clean = (reason or "").strip()
    suffix = f": {reason_clean}" if reason_clean else ""
    original_uid = locked.machine.uid
    new_reservation = Reservation.objects.create(
        machine=new_machine_locked,
        site=locked.site,
        start_date=remaining_start,
        end_date=remaining_end,
        person=locked.person,
        address=locked.address,
        notes=(
            f"[Wymiana po awarii maszyny {original_uid} (rezerwacja "
            f"#{locked.pk}) dnia {today}]{suffix}"
        ).strip(),
        status=Reservation.Status.POTWIERDZONA,
    )
    if actor is not None:
        new_reservation._history_user = actor  # type: ignore[attr-defined]
        # save_history dla create — simple-history snapshotuje na create()
        # przez post_save signal, więc trzeba nadpisać history_user na
        # ostatnim recordzie (signal działa SYNC w domyślnej konfiguracji,
        # więc HistoricalReservation już istnieje).
        last_hist = new_reservation.history.first()
        if last_hist is not None and last_hist.history_user_id != actor.pk:
            last_hist.history_user = actor
            last_hist.save(update_fields=["history_user"])

    # 2. Zamknij rezerwację oryginalną — end_date = today (jeśli była future),
    #    status = ZAKONCZONA, notatka z odwołaniem do nowej, replaced_by FK.
    if locked.end_date > today:
        locked.end_date = today
    locked.status = Reservation.Status.ZAKONCZONA
    closure_note = (
        f"[Wymieniona na {new_machine_locked.uid} (rezerwacja "
        f"#{new_reservation.pk}) dnia {today}]{suffix}"
    )
    locked.notes = (locked.notes + "\n" + closure_note).strip() if locked.notes else closure_note
    locked.replaced_by = new_reservation
    if actor is not None:
        locked._history_user = actor  # type: ignore[attr-defined]
    locked.save(
        update_fields=[
            "end_date",
            "status",
            "notes",
            "replaced_by",
            "updated_at",
        ]
    )

    # 3. Stara maszyna → W_SERWISIE. Wzorzec z ``report_breakdown`` (B-1):
    #    omijamy ``set_machine_to_service`` guard, bo:
    #      a) D6 guard sprawdza future POTWIERDZONA rezerwacje — jeśli takie
    #         są, pozostawiamy maszynę bez zmian (best-effort), operator
    #         decyduje ręcznie czy przenieść te bookingsy,
    #      b) NA_BUDOWIE guard nie ma sensu po swap'ie — rezerwacja właśnie
    #         się zamknęła, więc maszyna nie jest już "w polu" w sensie
    #         booking'owym, fizycznie magazynier ją zaraz przywiezie.
    #
    #    Logika: jeśli stara maszyna ma future bookings, zostaje bez zmian;
    #    inaczej bezpośredni setattr (z lockiem) na W_SERWISIE.
    machine_to_service_uid: str = ""
    # Wave 11 M-3 fix: reuse bulk-locked machine (zlockowane wcześniej w ordered pk batch)
    machine_locked = machines_by_pk[locked.machine_id]
    # Czy stara maszyna ma future POTWIERDZONA rezerwacje (poza tą właśnie
    # zamkniętą)? Jeśli tak — best-effort, zostawiamy bez zmiany.
    future_bookings_exist = (
        Reservation.objects.filter(
            machine_id=machine_locked.pk,
            status=Reservation.Status.POTWIERDZONA,
            start_date__gte=today,
        )
        .exclude(pk=locked.pk)
        .exists()
    )
    if future_bookings_exist:
        logger.warning(
            "swap_machine: maszyna %s ma future bookings, pomijam W_SERWISIE flip",
            machine_locked.uid,
        )
    elif machine_locked.status != machine_model.Status.W_SERWISIE:
        machine_locked.status = machine_model.Status.W_SERWISIE
        machine_locked.save(update_fields=["status", "updated_at"])
        machine_to_service_uid = machine_locked.uid

    logger.info(
        "swap_machine: rezerwacja %s (%s) → zamknięta dnia %s, "
        "nowa rezerwacja %s (%s) utworzona, maszyna do serwisu: %s",
        locked.pk,
        original_uid,
        today,
        new_reservation.pk,
        new_machine_locked.uid,
        machine_to_service_uid or "nie (best-effort)",
    )
    return {
        "original_id": locked.pk,
        "new_id": new_reservation.pk,
        "machine_to_service_uid": machine_to_service_uid or "",
    }


# =============================================================================
# BATCH RESERVATION  —  multi-maszynowa rezerwacja (B-7)
# =============================================================================


@transaction.atomic
def create_batch_reservation(
    *,
    machine_ids: list[int],
    site_id: int | None,
    start_date: date,
    end_date: date,
    person: str,
    address: str = "",
    notes: str = "",
    today: date | None = None,
    created_by=None,
) -> dict:
    """B-7 — utwórz N rezerwacji jako jedną grupę (batch).

    Use case biznesowy: kierownik budowy potrzebuje 5 łopat + 3 betoniarki +
    2 młoty pneumatyczne na 5 dni dla budowy BUD-2026-007. Zamiast tworzyć
    10 osobnych rezerwacji (10x kliknięć + 10x wypełnianie person/site/dat),
    magazynier wybiera maszyny multi-select, wpisuje wspólne pola RAZ →
    submit → system tworzy N rezerwacji, wszystkie z tym samym ``batch_id``.

    Atomic guarantee: jeśli którakolwiek maszyna ma konflikt lub niewłaściwy
    status (WYCOFANA / W_SERWISIE), CAŁY batch jest rollback'owany —
    "all or nothing". Lepiej dać magazynierowi natychmiastowy feedback
    o problemie niż zostawić go z połową rezerwacji utworzonych a połową
    odrzuconych (cognitive overhead, ryzyko duplikatów).

    Args:
        machine_ids: Lista PK :class:`machines.Machine` (1..MAX_BATCH_MACHINES).
        site_id: Opcjonalny PK :class:`ConstructionSite` (wspólny dla całej grupy).
        start_date: Wspólna data początku.
        end_date: Wspólna data końca.
        person: Wspólne imię i nazwisko osoby rezerwującej (wymagane).
        address: Wspólny adres dostawy (opcjonalny).
        notes: Wspólne notatki (opcjonalne).
        today: Opcjonalna data — ``freezegun`` w testach.

    Returns:
        ``{"batch_id": str (UUID), "created_count": int,
        "reservations": list[Reservation]}``.

    Raises:
        ValidationError: pusta lista maszyn, przekroczony limit, duplikaty
            w liście, niewłaściwy status maszyny, konflikt z istniejącymi
            rezerwacjami, walidacje wspólne (data końca < początku, dane
            w przeszłości, pusty person).
    """
    today = today or date.today()
    machine_model = apps.get_model("machines", "Machine")

    # ----------------------------------- walidacja parametrów wspólnych
    if not machine_ids:
        raise ValidationError(_("Wybierz minimum 1 maszynę dla grupy rezerwacji."))
    if len(machine_ids) > MAX_BATCH_MACHINES:
        raise ValidationError(
            _("Grupa może zawierać maksymalnie %(n)d maszyn. Podziel na mniejsze grupy.")
            % {"n": MAX_BATCH_MACHINES}
        )
    if len(set(machine_ids)) != len(machine_ids):
        raise ValidationError(
            _("Lista maszyn zawiera duplikaty — każda maszyna może być tylko raz.")
        )
    if not person or not person.strip():
        raise ValidationError({"person": _("Pole 'osoba rezerwująca' nie może być puste.")})
    if end_date < start_date:
        raise ValidationError({"end_date": _("Data końca musi być >= data początku.")})
    if end_date < today:
        raise ValidationError({"end_date": _("Nie można tworzyć rezerwacji w przeszłości.")})

    # ----------------------------------- lock + walidacja statusów maszyn
    # Lockujemy wszystkie maszyny w jednym query (mniej round-trips), order_by
    # PK żeby zapewnić deterministyczny lock order — eliminuje deadlock'i gdy
    # dwa równoległe batch'e wybierają nakładające się zestawy maszyn (klasyk:
    # tx A locks 1, 2, 3; tx B locks 3, 2, 1 → deadlock; oba sortują → wait chain).
    locked_machines = list(
        machine_model.objects.select_for_update().filter(pk__in=machine_ids).order_by("pk")
    )
    found_ids = {m.pk for m in locked_machines}
    missing_ids = set(machine_ids) - found_ids
    if missing_ids:
        raise ValidationError(
            _("Następujące maszyny nie istnieją: %(ids)s")
            % {"ids": ", ".join(str(i) for i in sorted(missing_ids))}
        )

    blocked_statuses = {machine_model.Status.WYCOFANA, machine_model.Status.W_SERWISIE}
    for machine in locked_machines:
        if machine.status in blocked_statuses:
            raise ValidationError(
                _("Maszyna %(uid)s ma status '%(status)s' — nie można jej zarezerwować.")
                % {"uid": machine.uid, "status": machine.get_status_display()}
            )

    # ----------------------------------- walidacja konfliktów per-maszyna
    # Najpierw zbieramy WSZYSTKIE konflikty (nie zatrzymujemy się na pierwszym),
    # żeby magazynier zobaczył pełną listę "co trzeba poprawić" zamiast
    # przeklikiwać submit N razy. UX: 5 błędów naraz > 5 osobnych retry.
    conflict_messages: list[str] = []
    for machine in locked_machines:
        if has_conflict(machine_id=machine.pk, start=start_date, end=end_date):
            conflicts = get_conflicting_reservations(
                machine_id=machine.pk, start=start_date, end=end_date
            )
            details = "; ".join(f"{r.start_date} - {r.end_date}" for r in conflicts[:3])
            conflict_messages.append(
                _("Maszyna %(uid)s: %(count)d kolidujących rezerwacji (%(details)s)")
                % {
                    "uid": machine.uid,
                    "count": len(conflicts),
                    "details": details,
                }
            )
    if conflict_messages:
        raise ValidationError(conflict_messages)

    # ----------------------------------- atomic create
    # ``bulk_create`` byłby szybszy ALE pomija ``simple_history`` snapshoty
    # (signal post_save jest wyłączony w bulk_create domyślnie). Wolimy
    # wolniejszą pętlę ``.create()`` żeby audit trail (HistoricalReservation)
    # miał wpis per-rezerwacja. N <= 50, wydajność nie jest problemem.
    batch_id = uuid.uuid4()
    person_clean = person.strip()
    address_clean = address.strip()
    created: list[Reservation] = []
    for machine in locked_machines:
        reservation = Reservation.objects.create(
            machine=machine,
            site_id=site_id,
            start_date=start_date,
            end_date=end_date,
            person=person_clean,
            address=address_clean,
            notes=notes,
            status=Reservation.Status.OCZEKUJACA,
            batch_id=batch_id,
            created_by=created_by,
        )
        created.append(reservation)

    logger.info(
        "Batch reservation created: %d maszyn, batch_id=%s, person=%s, "
        "start=%s, end=%s, site_id=%s",
        len(created),
        batch_id,
        person_clean,
        start_date,
        end_date,
        site_id,
    )
    return {
        "batch_id": str(batch_id),
        "created_count": len(created),
        "reservations": created,
    }


def _get_batch_reservations(batch_id: str | uuid.UUID) -> list[Reservation]:
    """Lock + return rezerwacje grupy o podanym UUID, sorted by PK.

    Pomocnicza do bulk action serwisów — jedno źródło prawdy o "co należy
    do batch'a". ``select_for_update`` chroni przed równoległym confirm /
    cancel / complete na pojedynczych rezerwacjach w trakcie bulk operacji.
    Sortowanie po PK zapewnia deterministyczny lock order → bez deadlock'ów.
    """
    return list(Reservation.objects.select_for_update().filter(batch_id=batch_id).order_by("pk"))


@transaction.atomic
def bulk_confirm_batch(
    batch_id: str | uuid.UUID,
    *,
    actor: AbstractBaseUser | None = None,
) -> dict[str, int | list[str]]:
    """Potwierdź wszystkie OCZEKUJACA rezerwacje w grupie batch.

    Iteruje po rezerwacjach grupy i wywołuje :func:`confirm_reservation`
    na każdej w stanie OCZEKUJACA. Pozostałe statusy (POTWIERDZONA,
    ZAKONCZONA, ANULOWANA) są skip'owane — bulk confirm jest idempotentny
    dla nie-pending rezerwacji (zamiast rzucać error per skip'ed item).

    Konflikt race-time na którejkolwiek rezerwacji → cały bulk rollback.

    Returns:
        ``{"confirmed_count": int, "skipped_count": int, "errors": list[str]}``.
    """
    reservations = _get_batch_reservations(batch_id)
    if not reservations:
        raise ValidationError(
            _("Grupa rezerwacji %(batch_id)s nie istnieje lub jest pusta.")
            % {"batch_id": str(batch_id)}
        )

    confirmed_count = 0
    skipped_count = 0
    errors: list[str] = []

    for reservation in reservations:
        if reservation.status != Reservation.Status.OCZEKUJACA:
            skipped_count += 1
            continue
        try:
            confirm_reservation(reservation)
            confirmed_count += 1
        except ValidationError as exc:
            # Konflikt race-time → zbieramy komunikat, kontynuujemy zbieranie
            # innych błędów, na końcu rzucamy wszystkie razem (rollback całości).
            errors.append(
                _("Rezerwacja %(uid)s #%(pk)d: %(msg)s")
                % {
                    "uid": reservation.machine.uid,
                    "pk": reservation.pk,
                    "msg": "; ".join(exc.messages),
                }
            )

    if errors:
        raise ValidationError(errors)

    logger.info(
        "Bulk confirm batch %s: confirmed=%d, skipped=%d (actor=%s)",
        batch_id,
        confirmed_count,
        skipped_count,
        actor.get_username() if actor is not None else "system",
    )
    return {
        "confirmed_count": confirmed_count,
        "skipped_count": skipped_count,
        "errors": [],
    }


@transaction.atomic
def bulk_cancel_batch(
    batch_id: str | uuid.UUID,
    *,
    reason: str,
    note: str = "",
    actor: AbstractBaseUser | None = None,
) -> dict[str, int]:
    """Anuluj wszystkie OCZEKUJACA + POTWIERDZONA rezerwacje w grupie batch.

    Iteruje po rezerwacjach i wywołuje :func:`cancel_reservation` z podanym
    ``reason`` na każdej w stanie non-terminal. ZAKONCZONA i ANULOWANA są
    skip'owane (cancel_reservation jest idempotent dla ANULOWANA, ale
    ZAKONCZONA rzuciłaby ValidationError — pomijamy explicit).

    ``reason`` jest wymagany dla całej grupy (jednolity powód = audit-friendly).
    Pozwala B-2 raportom miesięcznym agregować anulowane batch'e per powód.

    Returns:
        ``{"cancelled_count": int, "skipped_count": int}``.
    """
    if not reason:
        raise ValidationError({"cancellation_reason": _("Powód anulowania jest wymagany.")})

    reservations = _get_batch_reservations(batch_id)
    if not reservations:
        raise ValidationError(
            _("Grupa rezerwacji %(batch_id)s nie istnieje lub jest pusta.")
            % {"batch_id": str(batch_id)}
        )

    cancelled_count = 0
    skipped_count = 0
    for reservation in reservations:
        if reservation.status == Reservation.Status.ZAKONCZONA:
            skipped_count += 1
            continue
        # cancel_reservation jest idempotent dla ANULOWANA — zwraca bez zmian
        # (counter idzie do skipped). Sprawdzamy explicit żeby nie zaśmiecać
        # audit log'a kolejnymi save'ami bez zmian.
        if reservation.status == Reservation.Status.ANULOWANA:
            skipped_count += 1
            continue
        cancel_reservation(reservation, reason=reason, note=note)
        cancelled_count += 1

    logger.info(
        "Bulk cancel batch %s: cancelled=%d, skipped=%d, reason=%s (actor=%s)",
        batch_id,
        cancelled_count,
        skipped_count,
        reason,
        actor.get_username() if actor is not None else "system",
    )
    return {
        "cancelled_count": cancelled_count,
        "skipped_count": skipped_count,
    }


@transaction.atomic
def bulk_change_operator_batch(
    batch_id: str | uuid.UUID,
    *,
    new_person: str,
    actor: AbstractBaseUser | None = None,
) -> dict[str, int]:
    """Zmień osobę dla wszystkich aktywnych rezerwacji w grupie batch.

    Iteruje po rezerwacjach i wywołuje :func:`change_operator` na każdej
    w stanie non-terminal (OCZEKUJACA / POTWIERDZONA). Zamknięte (ZAKONCZONA
    / ANULOWANA) są skip'owane — change_operator i tak by je odrzucił,
    pomijamy je tutaj żeby nie zaśmiecać error listy.

    Use case: cała grupa była przypisana do "Tomek Kowalski", Tomek idzie
    na L4 — kierownik klika "Zmień operatora wszystkich" w batch detail,
    wpisuje "Sven Olsen", wszystkie aktywne rezerwacje dostają nową osobę.

    Returns:
        ``{"changed_count": int, "skipped_count": int}``.
    """
    new_person_clean = (new_person or "").strip()
    if not new_person_clean:
        raise ValidationError({"new_person": _("Nowa osoba jest wymagana.")})
    if len(new_person_clean) < MIN_OPERATOR_NAME_LENGTH:
        raise ValidationError(
            {
                "new_person": _("Imię i nazwisko musi mieć co najmniej %(n)d znaki.")
                % {"n": MIN_OPERATOR_NAME_LENGTH}
            }
        )

    reservations = _get_batch_reservations(batch_id)
    if not reservations:
        raise ValidationError(
            _("Grupa rezerwacji %(batch_id)s nie istnieje lub jest pusta.")
            % {"batch_id": str(batch_id)}
        )

    changed_count = 0
    skipped_count = 0
    errors: list[str] = []
    for reservation in reservations:
        if reservation.is_closed:
            skipped_count += 1
            continue
        # Jeśli new_person == current_person (case-insensitive) — change_operator
        # rzuci "Nowa osoba musi się różnić". Skipujemy żeby bulk był idempotent
        # gdy część rezerwacji ma już docelową osobę (re-run safe).
        if new_person_clean.casefold() == reservation.person.strip().casefold():
            skipped_count += 1
            continue
        try:
            change_operator(reservation, new_person=new_person_clean, actor=actor)
            changed_count += 1
        except ValidationError as exc:
            errors.append(
                _("Rezerwacja %(uid)s #%(pk)d: %(msg)s")
                % {
                    "uid": reservation.machine.uid,
                    "pk": reservation.pk,
                    "msg": "; ".join(exc.messages),
                }
            )

    if errors:
        raise ValidationError(errors)

    logger.info(
        "Bulk change operator batch %s: changed=%d, skipped=%d, new_person=%s (actor=%s)",
        batch_id,
        changed_count,
        skipped_count,
        new_person_clean,
        actor.get_username() if actor is not None else "system",
    )
    return {
        "changed_count": changed_count,
        "skipped_count": skipped_count,
    }
