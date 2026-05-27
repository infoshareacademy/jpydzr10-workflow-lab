"""URL routing aplikacji accounts."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.PlanerLoginView.as_view(), name="login"),
    path("logout/", views.PlanerLogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    # Strona docelowa dla ``AXES_LOCKOUT_URL`` — pokazywana po przekroczeniu
    # limitu nieudanych prób logowania (5 prób per username+ip → 1h lockout).
    path("zablokowane/", views.AxesLockedView.as_view(), name="locked"),
    # Wave 14-F O-1: UI dla register_employee service. Audyt Wave 14-E
    # zidentyfikował że service istniał ale nie miał view'a — operator
    # mógł tworzyć pracowników tylko przez /admin/auth/user/add/ (raw
    # Django form bez HIBP + bez profile setup w jednym kroku).
    path("pracownicy/", views.EmployeeListView.as_view(), name="employee_list"),
    path("pracownicy/dodaj/", views.employee_register_view, name="employee_register"),
    path(
        "pracownicy/<int:pk>/zwolnij/",
        views.employee_terminate_view,
        name="employee_terminate",
    ),
    path(
        "pracownicy/<int:pk>/anonimizuj/",
        views.employee_anonymize_view,
        name="employee_anonymize",
    ),
]
