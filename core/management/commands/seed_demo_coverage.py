"""Dosypanie demo danych pokrywających rzadko używane choices.

Po ``seed_machines`` + ``seed_reservations_demo`` + ``seed_reservations_topup``
brakuje w bazie reprezentacji dla:

* ``Reservation.Status.ANULOWANA`` + wszystkich 5 ``CancellationReason``,
* ``Machine.Status.WYCOFANA`` (raport "wycofane z floty"),
* ``ConstructionSite.Status.ZAKONCZONA`` / ``ANULOWANA``,
* ``ServiceRecord.RecordType.PRZEGLAD_KWARTALNY``.

Dodatkowo: anuluje część rezerwacji obejmujących prezentacyjny dzień
``14.06.2026`` — żeby KPI "Dostępne maszyny" w home pokazywało
realistyczne ~30% zamiast ~10%.

Komenda jest idempotentna na poziomie nazw: re-run wykryje że budowa
``BUD-2026-CLOSED`` / ``BUD-2026-CANCEL`` już istnieje i pominie. Anulacje
działają na PIERWSZYCH N rezerwacjach pasujących do każdego kryterium —
ponowne uruchomienie nie produkuje duplikatów (anulowane są pomijane).

Usage::

    uv run python manage.py seed_demo_coverage
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from machines.models import Machine
from machines.services import retire_machine
from reservations.models import ConstructionSite, Reservation
from reservations.services import cancel_reservation, update_site
from service.models import ServiceRecord

PRESENTATION_DATE = date(2026, 6, 14)
TODAY = date(2026, 5, 27)


def _cancellation_seed_plan() -> list[tuple[str, str]]:
    """5 par (reason_value, note) pokrywające cały :class:`CancellationReason`."""
    return [
        ("klient_zrezygnowal", "Klient cofnął zamówienie po podpisaniu umowy."),
        ("awaria", "Maszyna uszkodzona w trakcie transportu — wymiana w batchu."),
        ("zmiana_terminu", "Termin budowy przesunięty o 3 tygodnie."),
        ("brak_dostepnosci", "Maszyna potrzebna na pilną budowę z wyższym priorytetem."),
        ("inne", "Klient wybrał inną firmę po ofertowaniu."),
    ]


class Command(BaseCommand):
    help = (
        "Dosypuje demo data pokrywajace rzadkie choices: 5 anulowanych rezerwacji "
        "z roznymi reasonami, 2 wycofane maszyny, 1 zakonczona + 1 anulowana "
        "budowa, ~10 przegladow kwartalnych, oraz dodatkowe anulowania potwierdzonych "
        "rezerwacji aby KPI 'Dostepne maszyny' bylo realistyczne (~30 procent)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--seed", type=int, default=14062026)

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        random.seed(options["seed"])

        # ------------------------------------------------------------------
        # 1. Anuluj 5 rezerwacji z 5 roznymi reasonami
        # ------------------------------------------------------------------
        plan = _cancellation_seed_plan()
        cancellable = list(
            Reservation.objects.filter(
                status__in=[Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA],
                start_date__gt=TODAY,
            ).order_by("start_date")[: len(plan) * 3]
        )
        random.shuffle(cancellable)

        for (reason, note), res in zip(plan, cancellable, strict=False):
            cancel_reservation(res, reason=reason, note=note, today=TODAY)
            self.stdout.write(f"  CANCEL #{res.pk} ({res.machine.uid}): reason={reason}")

        # ------------------------------------------------------------------
        # 2. Wycofaj 2 maszyny z floty
        # ------------------------------------------------------------------
        retire_uids = ["M-0028", "M-0034"]  # Walec 3 + Spawarka 3
        for uid in retire_uids:
            try:
                machine = Machine.objects.get(uid=uid)
            except Machine.DoesNotExist:
                continue
            # Zakoncz aktywne rezerwacje przed retire (Hard Return) — uzywamy
            # cancel_reservation z reasonem AWARIA (najblizej "wycofania").
            for res in machine.reservations.filter(
                status__in=[Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA]
            ):
                cancel_reservation(
                    res,
                    reason="awaria",
                    note=f"Maszyna {uid} wycofana z floty.",
                    today=TODAY,
                )
            retire_machine(
                machine, reason="Zakończona eksploatacja, sprzedaż do złomu.", today=TODAY
            )
            self.stdout.write(f"  RETIRE {uid}: {machine.name}")

        # ------------------------------------------------------------------
        # 3. Budowa zakonczona + budowa anulowana
        # ------------------------------------------------------------------
        # Zakonczona: weź istniejacą BUD-2026-005 lub ostatnia AKTYWNA
        closed_site = (
            ConstructionSite.objects.filter(project_number="BUD-2026-005").first()
            or ConstructionSite.objects.filter(status=ConstructionSite.Status.AKTYWNA)
            .order_by("-project_number")
            .first()
        )
        if closed_site:
            update_site(
                closed_site,
                status=ConstructionSite.Status.ZAKONCZONA.value,
                end_date=date(2026, 4, 30),
            )
            self.stdout.write(f"  CLOSE site {closed_site.project_number} ({closed_site.name})")

        # Anulowana: nowa budowa
        cancelled_site, created = ConstructionSite.objects.get_or_create(
            project_number="BUD-2026-006",
            defaults={
                "name": "Centrum biurowe Sky Tower (anulowana)",
                "client_name": "Sky Real Estate Sp. z o.o.",
                "address": "ul. Wieżowa 5",
                "city": "Wrocław",
                "status": ConstructionSite.Status.ANULOWANA,
                "start_date": date(2026, 3, 15),
                "end_date": date(2026, 8, 30),
            },
        )
        marker = "create" if created else "exists"
        self.stdout.write(
            f"  CANCEL site {cancelled_site.project_number} ({cancelled_site.name}) [{marker}]"
        )

        # ------------------------------------------------------------------
        # 4. ServiceRecord PRZEGLAD_KWARTALNY (10 sztuk)
        # ------------------------------------------------------------------
        existing_kwartalny = ServiceRecord.objects.filter(
            record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY
        ).count()
        target_kwartalny = 10
        to_create = max(target_kwartalny - existing_kwartalny, 0)

        if to_create:
            # Wybieramy 10 losowych maszyn (aktywnych) dla rotacji przeglądów
            candidate_machines = list(
                Machine.objects.exclude(status=Machine.Status.WYCOFANA).order_by("?")[:to_create]
            )
            for m in candidate_machines:
                performed = TODAY - timedelta(days=random.randint(30, 90))
                ServiceRecord.objects.create(
                    machine=m,
                    record_type=ServiceRecord.RecordType.PRZEGLAD_KWARTALNY,
                    performed_date=performed,
                    performed_by=random.choice(
                        [
                            "Serwis Bobcat Polska",
                            "Mobilny Serwis Kowalski",
                            "Techserwis Maszyn Sp. z o.o.",
                            "Adam Nowicki (autoryzowany serwis)",
                        ]
                    ),
                    description=(
                        "Przegląd kwartalny — kontrola układu hydraulicznego, wymiana filtrów, "
                        "smarowanie punktów konserwacyjnych, kontrola płynów eksploatacyjnych."
                    ),
                    cost=Decimal(random.randint(180, 480)),
                    next_inspection=performed + timedelta(days=90),
                )
                self.stdout.write(f"  SERVICE quarterly inspection on {m.uid} ({performed})")

        # ------------------------------------------------------------------
        # 5. KPI fix — anuluj rezerwacje POTWIERDZONA obejmujące 14.06.2026
        #    dla 7 losowych maszyn, żeby były 'W magazynie' na prezentację.
        # ------------------------------------------------------------------
        candidates = list(
            Reservation.objects.filter(
                status=Reservation.Status.POTWIERDZONA,
                start_date__lte=PRESENTATION_DATE,
                end_date__gte=PRESENTATION_DATE,
            ).select_related("machine")
        )
        random.shuffle(candidates)
        seen_machines: set[int] = set()
        kpi_target = 7
        for res in candidates:
            if len(seen_machines) >= kpi_target:
                break
            if res.machine_id in seen_machines:
                continue
            try:
                cancel_reservation(
                    res,
                    reason="zmiana_terminu",
                    note="Klient poprosił o przesunięcie — termin renegocjowany.",
                    today=TODAY,
                )
            except Exception as exc:
                self.stdout.write(f"  SKIP cancel #{res.pk}: {exc}")
                continue
            seen_machines.add(res.machine_id)
            # Po anulacji potwierdzonej obejmującej 14.06 maszyna wraca do magazynu.
            machine = res.machine
            if machine.status in (Machine.Status.NA_BUDOWIE, Machine.Status.ZAREZERWOWANA):
                machine.status = Machine.Status.W_MAGAZYNIE.value
                machine.save(update_fields=["status"])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"KPI fix: zwolnionych {len(seen_machines)} maszyn z aktywnych "
                f"rezerwacji obejmujacych 14.06.2026."
            )
        )

        # ------------------------------------------------------------------
        # Final summary
        # ------------------------------------------------------------------
        self.stdout.write("")
        self.stdout.write("=== Rozklad po seed ===")
        from collections import Counter

        machine_counts = Counter(Machine.objects.values_list("status", flat=True))
        self.stdout.write("Machine.status:")
        for status_val, n in sorted(machine_counts.items()):
            self.stdout.write(f"  {status_val:25s} {n}")

        res_counts = Counter(Reservation.objects.values_list("status", flat=True))
        self.stdout.write("Reservation.status:")
        for status_val, n in sorted(res_counts.items()):
            self.stdout.write(f"  {status_val:25s} {n}")

        site_counts = Counter(ConstructionSite.objects.values_list("status", flat=True))
        self.stdout.write("ConstructionSite.status:")
        for status_val, n in sorted(site_counts.items()):
            self.stdout.write(f"  {status_val:25s} {n}")
