"""Tworzy domyślne grupy RBAC i przypisuje im permissions Django auth.

Trzy grupy odpowiadają wartościom enum :class:`EmployeeProfile.Function`
(montażysta celowo nie ma grupy — read-only access przez login_required):

* **Magazynierzy** — pełny CRUD rezerwacji i budów, view/edit maszyn, wpisy serwisowe.
* **Kierownicy** — składanie wniosków o rezerwacje (add/view, BEZ zatwierdzania),
  budowy (add/change/delete), dodawanie wpisów serwisowych.
* **Administratorzy** — wszystkie permissions w obrębie 4 aplikacji domenowych.

Idempotent: kolejne uruchomienia tylko synchronizują permissions
(:meth:`Group.permissions.set`) nie modyfikując ad-hoc grup spoza tej listy.
Wywołanie zalecane:

* po fresh ``migrate`` (przed seedem),
* po dodaniu nowego modelu / permission (aby zsynchronizować role).
"""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

# Mapping: nazwa grupy → lista "{app_label}.{codename}" permission identifiers.
# Trzymane tu w jednym miejscu (a nie w services.py) bo to setup runtime — nie
# logika biznesowa. Sync z FUNCTION_GROUP_MAP keys.
GROUPS_PERMISSIONS: dict[str, list[str]] = {
    "Magazynierzy": [
        # Pełny CRUD rezerwacji.
        "reservations.add_reservation",
        "reservations.change_reservation",
        "reservations.delete_reservation",
        "reservations.view_reservation",
        # Budowy — add/change/view (delete tylko Kierownicy/Admini).
        "reservations.add_constructionsite",
        "reservations.change_constructionsite",
        "reservations.view_constructionsite",
        # Maszyny — view + change (np. zwrot, do serwisu).
        "machines.view_machine",
        "machines.change_machine",
        # Wpisy serwisowe — view + add + change.
        "service.view_servicerecord",
        "service.add_servicerecord",
        "service.change_servicerecord",
    ],
    "Kierownicy": [
        # Rezerwacje: kierownik SKŁADA wnioski (add → rezerwacja oczekująca),
        # ale NIE zatwierdza/edytuje — to robi magazynier lub admin. Stąd brak
        # change_reservation (potwierdzanie/anulowanie/edycja = magazynier/admin;
        # sama edycja formularza = wyłącznie admin/superuser).
        "reservations.add_reservation",
        "reservations.view_reservation",
        "reservations.add_constructionsite",
        "reservations.change_constructionsite",
        "reservations.delete_constructionsite",
        "reservations.view_constructionsite",
        "machines.view_machine",
        "service.view_servicerecord",
        "service.add_servicerecord",
    ],
    # Administratorzy dostają wszystkie permissions z 4 aplikacji domenowych —
    # listę kompilujemy dynamicznie w handle() (sentinel "*").
    "Administratorzy": ["*"],
}

# Aplikacje domenowe dla wildcard'u "*" (Administratorzy). Nie wciągamy ``auth``
# żeby admin nie miał default'owo permissions do tworzenia userów / grup —
# to powinno wymagać is_staff/is_superuser eskalacji.
ADMIN_APPS: tuple[str, ...] = ("machines", "reservations", "service", "accounts")


class Command(BaseCommand):
    help = "Tworzy domyślne grupy RBAC + przypisuje permissions."

    def handle(self, *args, **options):
        created = 0
        synced = 0
        for group_name, perm_codes in GROUPS_PERMISSIONS.items():
            group, was_created = Group.objects.get_or_create(name=group_name)
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Utworzono grupę: {group_name}"))

            if perm_codes == ["*"]:
                # Admini dostają wszystkie permissions z aplikacji domenowych.
                content_types = ContentType.objects.filter(app_label__in=ADMIN_APPS)
                permissions = Permission.objects.filter(content_type__in=content_types)
            else:
                permissions = []
                for code in perm_codes:
                    app_label, codename = code.split(".", 1)
                    try:
                        perm = Permission.objects.get(
                            content_type__app_label=app_label,
                            codename=codename,
                        )
                        permissions.append(perm)
                    except Permission.DoesNotExist:
                        self.stderr.write(
                            self.style.WARNING(
                                f"  Pominięto brakujące permission: {code} "
                                f"(czy migracje są aktualne?)"
                            )
                        )

            group.permissions.set(permissions)
            synced += 1
            self.stdout.write(f"  {group_name}: {group.permissions.count()} permissions")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nZakończono: {created} grup utworzonych, {synced} grup zsynchronizowanych."
            )
        )
