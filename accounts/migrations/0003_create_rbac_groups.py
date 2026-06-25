"""Tworzy grupy RBAC (Magazynierzy, Kierownicy, Administratorzy) wraz z ich
uprawnieniami — wcześniej robił to wyłącznie ręczny ``setup_groups``, przez co
świeża baza miała pustą tabelę grup i każdy widok ``permission_required``
zwracał 403 dla nie-superuserów.

Migracja jest idempotentna (``get_or_create`` + ``permissions.set``), więc
ponowne uruchomienie tylko synchronizuje uprawnienia. ``setup_groups`` pozostaje
jako pomocnik do ręcznej re-synchronizacji po dodaniu nowego modelu.
"""

from __future__ import annotations

from django.db import migrations

# Mapa: nazwa grupy → lista "{app_label}.{codename}" albo sentinel "*" (komplet
# uprawnień z aplikacji domenowych). Trzymana w migracji (self-contained), żeby
# odtwarzała się deterministycznie przy każdym `migrate` niezależnie od kodu app.
GROUPS_PERMISSIONS: dict[str, list[str]] = {
    "Magazynierzy": [
        "reservations.add_reservation",
        "reservations.change_reservation",
        "reservations.delete_reservation",
        "reservations.view_reservation",
        "reservations.add_constructionsite",
        "reservations.change_constructionsite",
        "reservations.view_constructionsite",
        "machines.view_machine",
        "machines.change_machine",
        "service.view_servicerecord",
        "service.add_servicerecord",
        "service.change_servicerecord",
    ],
    "Kierownicy": [
        "reservations.add_reservation",
        "reservations.change_reservation",
        "reservations.view_reservation",
        "reservations.add_constructionsite",
        "reservations.change_constructionsite",
        "reservations.delete_constructionsite",
        "reservations.view_constructionsite",
        "machines.view_machine",
        "service.view_servicerecord",
        "service.add_servicerecord",
    ],
    "Administratorzy": ["*"],
}

# Aplikacje domenowe rozwijane przez sentinel "*" (Administratorzy). Bez ``auth``
# — tworzenie userów/grup wymaga eskalacji do is_staff/is_superuser.
ADMIN_APPS: tuple[str, ...] = ("machines", "reservations", "service", "accounts")

ALL_GROUP_NAMES = list(GROUPS_PERMISSIONS.keys())


def _ensure_permissions_exist() -> None:
    """Wymusza utworzenie ContentType + Permission dla aplikacji domenowych.

    Uprawnienia są normalnie tworzone przez sygnał ``post_migrate``, który
    odpala się dopiero PO wszystkich migracjach w danym przebiegu ``migrate``.
    Na świeżej bazie oznaczałoby to, że w trakcie tej migracji uprawnień jeszcze
    nie ma i grupy powstałyby puste. Tworzymy je tu jawnie, aby RBAC działał już
    po pierwszym ``migrate``.
    """
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    for app_label in ADMIN_APPS:
        app_config = global_apps.get_app_config(app_label)
        create_contenttypes(app_config, verbosity=0)
        create_permissions(app_config, verbosity=0)


def create_groups(apps, schema_editor):
    """Tworzy grupy i przypisuje uprawnienia. Idempotentne."""
    _ensure_permissions_exist()

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    for group_name, perm_codes in GROUPS_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=group_name)

        if perm_codes == ["*"]:
            content_types = ContentType.objects.filter(app_label__in=ADMIN_APPS)
            group.permissions.set(Permission.objects.filter(content_type__in=content_types))
            continue

        perms = []
        for code in perm_codes:
            app_label, codename = code.split(".", 1)
            # ``filter(...).first()`` zamiast ``get`` — brak uprawnienia nie
            # wysadza migracji (tolerujemy częściowy stan), tylko je pomija.
            perm = Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename,
            ).first()
            if perm is not None:
                perms.append(perm)
        group.permissions.set(perms)


def remove_groups(apps, schema_editor):
    """Reverse: usuwa utworzone grupy."""
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ALL_GROUP_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_employeeprofile_anonymized_at_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("machines", "0005_fix_machine_names"),
        ("reservations", "0007_realistic_pl_data"),
        ("service", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_groups, remove_groups),
    ]
