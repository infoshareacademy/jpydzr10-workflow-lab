"""Synchronizuje grupę Kierownicy z kanonem uprawnień (setup_groups.py).

Migracja ``0003_create_rbac_groups`` przyznała Kierownicy
``reservations.change_reservation``, ale kanoniczna definicja
(``accounts/management/commands/setup_groups.py``) tego uprawnienia NIE zawiera:
kierownik SKŁADA wnioski (add), a potwierdza/anuluje magazynier lub admin.
Bez tej migracji baza z migracji rozjeżdża się z kanonem i kierownik może
potwierdzać rezerwacje wbrew regule RBAC.
"""

from django.db import migrations


def _drop_change_reservation(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perm = Permission.objects.filter(
        content_type__app_label="reservations",
        codename="change_reservation",
    ).first()
    if perm is None:
        return
    group = Group.objects.filter(name="Kierownicy").first()
    if group is not None:
        group.permissions.remove(perm)


def _restore_change_reservation(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perm = Permission.objects.filter(
        content_type__app_label="reservations",
        codename="change_reservation",
    ).first()
    if perm is None:
        return
    group = Group.objects.filter(name="Kierownicy").first()
    if group is not None:
        group.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_employeeprofile_preferred_language_and_more"),
        ("reservations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_drop_change_reservation, _restore_change_reservation),
    ]
