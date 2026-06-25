"""URL routing for the service app (mounted at ``/serwis/`` in the project)."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "service"

urlpatterns = [
    path("", views.ServiceRecordListView.as_view(), name="list"),
    path("dodaj/", views.ServiceRecordCreateView.as_view(), name="create"),
    path("bulk-przeglady/", views.BulkInspectionView.as_view(), name="bulk_inspection"),
    path("raporty/", views.ReportPageView.as_view(), name="reports"),
    path("raporty/dane.json", views.ReportDataView.as_view(), name="report_data"),
    path(
        "raporty/xlsx/<int:year>/<int:quarter>/",
        views.ReportXlsxView.as_view(),
        name="report_xlsx",
    ),
    path(
        "eksport/wszystkie.xlsx",
        views.AllServiceRecordsXlsxView.as_view(),
        name="export_all_xlsx",
    ),
    path(
        "eksport/maszyna/<str:uid>.xlsx",
        views.MachineServiceXlsxView.as_view(),
        name="export_machine_xlsx",
    ),
    path("<int:pk>/", views.ServiceRecordDetailView.as_view(), name="detail"),
    path("<int:pk>/edytuj/", views.ServiceRecordUpdateView.as_view(), name="update"),
    path("<int:pk>/pdf/", views.InspectionPdfView.as_view(), name="pdf"),
    path("<int:pk>/usun/", views.ServiceRecordDeleteView.as_view(), name="delete"),
    path("<int:pk>/zakoncz-serwis/", views.close_service_view, name="close_service"),
]
