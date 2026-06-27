"""django-unfold dashboard callback — KPI cards na admin landing page.

Funkcja podpieta przez ``UNFOLD["DASHBOARD_CALLBACK"]`` w
``planer_config/settings/base.py``. Otrzymuje request + context, zwraca
wzbogacony context z `kpi` ktore unfold renderuje w widoku startowym.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def callback(request, context: dict[str, Any]) -> dict[str, Any]:
    """Wstrzykuje 4 KPI cards do unfold admin dashboard.

    1. Dostepne maszyny (W magazynie / Total)
    2. Aktywne rezerwacje (potwierdzone + oczekujace)
    3. Przeglady przeterminowane
    4. Budowy aktywne
    """
    # Lazy import — modele ladowane po app registry.
    from machines.models import INSPECTION_WARNING_DAYS, Machine
    from reservations.models import ConstructionSite, Reservation

    today = date.today()
    horizon = today + timedelta(days=INSPECTION_WARNING_DAYS)

    try:
        machines_available = Machine.objects.filter(status="W magazynie").count()
        machines_total = Machine.objects.count()
        machines_on_site = Machine.objects.filter(status="Na budowie").count()

        reservations_active = Reservation.objects.filter(
            status__in=("oczekująca", "potwierdzona")
        ).count()
        reservations_pending = Reservation.objects.filter(status="oczekująca").count()

        inspections_overdue = (
            Machine.objects.filter(inspection_date__lt=today)
            .exclude(inspection_date__isnull=True)
            .count()
        )
        inspections_upcoming = Machine.objects.filter(
            inspection_date__gte=today, inspection_date__lte=horizon
        ).count()

        sites_active = ConstructionSite.objects.filter(status="aktywna").count()
    except Exception:
        # Defensywnie — przy pierwszej migracji tabele moga nie istniec.
        machines_available = machines_total = machines_on_site = 0
        reservations_active = reservations_pending = 0
        inspections_overdue = inspections_upcoming = 0
        sites_active = 0

    try:
        machines_url = reverse("admin:machines_machine_changelist")
        reservations_url = reverse("admin:reservations_reservation_changelist")
        sites_url = reverse("admin:reservations_constructionsite_changelist")
    except Exception:
        machines_url = reservations_url = sites_url = "/admin/"

    context.update(
        {
            "kpi": [
                {
                    "title": _("Dostępne maszyny"),
                    "metric": f"{machines_available} / {machines_total}",
                    "footer": _("%(count)s na budowie") % {"count": machines_on_site},
                    "url": f"{machines_url}?status__exact=W+magazynie",
                },
                {
                    "title": _("Aktywne rezerwacje"),
                    "metric": str(reservations_active),
                    "footer": _("%(count)s oczekujących") % {"count": reservations_pending},
                    "url": reservations_url,
                },
                {
                    "title": _("Przeglądy przeterminowane"),
                    "metric": str(inspections_overdue),
                    "footer": _("%(count)s w 14 dniach") % {"count": inspections_upcoming},
                    "url": machines_url,
                },
                {
                    "title": _("Aktywne budowy"),
                    "metric": str(sites_active),
                    "footer": _("Otwarte projekty"),
                    "url": sites_url,
                },
            ],
        }
    )
    return context
