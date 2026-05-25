"""Sygnały aplikacji accounts (auto-tworzenie profilu, sync grup RBAC)."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import EmployeeProfile
from .services import FUNCTION_GROUP_MAP


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_employee_profile(sender, instance, created, **kwargs):
    """Tworzy EmployeeProfile dla każdego nowego użytkownika.

    Zabezpieczenie `hasattr(instance, "profile")` chroni przed race condition
    przy importach fixtures (django może wywołać post_save kilka razy).
    """
    if created and not hasattr(instance, "profile"):
        EmployeeProfile.objects.create(user=instance)


@receiver(post_save, sender=EmployeeProfile)
def sync_groups_on_employee_save(sender, instance, created, **kwargs):
    """Synchronizuje członkostwo w Group na podstawie EmployeeProfile.function.

    Przy zmianie funkcji pracownika: usuwa go z poprzednich grup function-related
    i dodaje do nowych zgodnie z FUNCTION_GROUP_MAP. Gdy profil jest
    zanonimizowany lub nieaktywny — czyści wszystkie grupy (revoke RBAC).
    """
    if instance.is_anonymized or not instance.is_active_employee:
        instance.user.groups.clear()
        return

    target_groups = FUNCTION_GROUP_MAP.get(instance.function, [])
    function_managed_groups = {name for names in FUNCTION_GROUP_MAP.values() for name in names}
    user_groups = instance.user.groups.all()
    for group in user_groups:
        if group.name in function_managed_groups and group.name not in target_groups:
            instance.user.groups.remove(group)
    for group_name in target_groups:
        group, _ = Group.objects.get_or_create(name=group_name)
        instance.user.groups.add(group)
