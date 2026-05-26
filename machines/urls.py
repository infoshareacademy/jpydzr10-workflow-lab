"""URL routing for the machines app (mounted at ``/maszyny/`` in the project).

UIDs are used directly as URL slugs — ``[\\w\\-]+`` matches A-Z, 0-9, ``_``,
``-`` (mirrors :data:`machines.models.UID_VALIDATOR`). Dots/spaces/slashes
are rejected at the routing layer, so ``M..0001``-style edge cases never
reach the view.
"""

from django.urls import path, re_path

from . import views

app_name = "machines"

urlpatterns = [
    path("", views.MachineListView.as_view(), name="list"),
    path("dodaj/", views.MachineCreateView.as_view(), name="create"),
    path("import/", views.MachineImportXlsxView.as_view(), name="import_xlsx"),
    path("eksport/", views.MachineExportXlsxView.as_view(), name="export_xlsx"),
    # Wave 14-F D-3: HTMX modal partial — overdue + upcoming inspections.
    # MUSI być PRZED ``re_path(<uid>)`` (pattern [\w\-]+ matchowałby
    # "przeglady-w-14d" jako uid → 404 lub niewłaściwy view).
    path(
        "przeglady-w-14d/",
        views.inspections_due_modal_view,
        name="inspections_due_modal",
    ),
    re_path(r"^(?P<uid>[\w\-]+)/$", views.MachineDetailView.as_view(), name="detail"),
    re_path(r"^(?P<uid>[\w\-]+)/edytuj/$", views.MachineUpdateView.as_view(), name="update"),
    re_path(r"^(?P<uid>[\w\-]+)/usun/$", views.MachineDeleteView.as_view(), name="delete"),
    re_path(
        r"^(?P<uid>[\w\-]+)/serwis/$",
        views.MachineSetServiceView.as_view(),
        name="set_service",
    ),
    re_path(
        r"^(?P<uid>[\w\-]+)/zwrot/$",
        views.MachineReturnView.as_view(),
        name="return",
    ),
    re_path(
        r"^(?P<uid>[\w\-]+)/zakoncz-naprawe/$",
        views.MachineCloseRepairView.as_view(),
        name="close_repair",
    ),
    re_path(
        r"^(?P<uid>[\w\-]+)/wycofaj/$",
        views.MachineRetireView.as_view(),
        name="retire",
    ),
]
