"""URL routing for the reservations app.

Top-level prefix ``/rezerwacje/`` is added in ``planer_config/urls.py``.
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    # ---------------------------------------------------------------- sites
    # NOTE: the site routes come BEFORE the reservation detail route so the
    # path ``/rezerwacje/budowy/`` is matched first (otherwise Django would
    # try to coerce ``"budowy"`` into an int for the reservation detail PK).
    path("budowy/", views.ConstructionSiteListView.as_view(), name="site_list"),
    path("budowy/dodaj/", views.site_create, name="site_create"),
    path("budowy/dodaj-inline/", views.site_inline_create, name="site_inline_create"),
    path("budowy/<int:pk>/", views.ConstructionSiteDetailView.as_view(), name="site_detail"),
    path("budowy/<int:pk>/edytuj/", views.site_update, name="site_update"),
    path("budowy/<int:pk>/usun/", views.site_delete, name="site_delete"),
    # ---------------------------------------------------------------- HTMX
    path("check-konflikt/", views.CheckConflictView.as_view(), name="check_conflict"),
    # ---------------------------------------------------------------- timeline
    path("timeline/", views.TimelineView.as_view(), name="timeline"),
    # Ręczne uruchomienie daily-sync z UI (staff only — sprawdzane w view).
    path("sync-statusy/", views.daily_sync_now_view, name="daily_sync_now"),
    path("szybka-rezerwacja/", views.QuickReserveView.as_view(), name="quick_reserve"),
    # Wave 14-A Bundle 3 -- timeline klik PUSTY cell -> pelen ReservationForm modal.
    # MUSI byc PRZED `<int:pk>/modal/` zeby /quick-modal/ nie zostal sparsowany
    # jako pk='quick-modal' (failure przez int converter).
    path(
        "quick-modal/",
        views.reservation_quick_modal_view,
        name="quick_modal",
    ),
    # ---------------------------------------------------------------- B-7 batch
    # Routes MUST come BEFORE ``<int:pk>/`` detail so ``/grupa/`` nie próbuje
    # być zinterpretowane jako pk=grupa (failwave przez int converter).
    path("grupa/dodaj/", views.batch_create_view, name="batch_create"),
    path("grupa/<uuid:batch_id>/", views.batch_detail_view, name="batch_detail"),
    path(
        "grupa/<uuid:batch_id>/potwierdz-wszystkie/",
        views.batch_bulk_confirm,
        name="batch_bulk_confirm",
    ),
    path(
        "grupa/<uuid:batch_id>/anuluj-wszystkie/",
        views.batch_bulk_cancel,
        name="batch_bulk_cancel",
    ),
    path(
        "grupa/<uuid:batch_id>/zmien-operatora-wszystkim/",
        views.batch_bulk_change_operator,
        name="batch_bulk_change_operator",
    ),
    # ---------------------------------------------------------------- list / detail / CRUD
    path("", views.ReservationListView.as_view(), name="list"),
    path("dodaj/", views.reservation_create, name="create"),
    path("<int:pk>/", views.ReservationDetailView.as_view(), name="detail"),
    # Wave 14-A Bundle 2 -- modal "klik bar na timeline -> popup pelnej rezerwacji".
    path("<int:pk>/modal/", views.reservation_modal_view, name="modal"),
    path("<int:pk>/pdf/", views.ReservationPDFView.as_view(), name="pdf"),
    path("<int:pk>/edytuj/", views.ReservationUpdateView.as_view(), name="update"),
    path("<int:pk>/potwierdz/", views.reservation_confirm, name="confirm"),
    path("<int:pk>/anuluj/", views.reservation_cancel, name="cancel"),
    path("<int:pk>/zakoncz/", views.reservation_complete, name="complete"),
    path("<int:pk>/awaria/", views.reservation_report_breakdown, name="report_breakdown"),
    # B-4: zmiana osoby przypisanej do rezerwacji (audit via simple-history)
    path("<int:pk>/zmien-osobe/", views.reservation_change_operator, name="change_operator"),
    # B-6: wymiana maszyny mid-reservation (kończy starą, tworzy nową)
    path("<int:pk>/wymien-maszyne/", views.reservation_swap_machine, name="swap_machine"),
]
