"""Admin registration smoke tests for the service app."""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import site

from service.admin import ServiceRecordAdmin
from service.factories import InspectionFactory
from service.models import ServiceRecord


@pytest.mark.django_db
def test_service_record_is_registered():
    assert site.is_registered(ServiceRecord)


@pytest.mark.django_db
def test_admin_class_uses_simple_history():
    from simple_history.admin import SimpleHistoryAdmin

    assert issubclass(ServiceRecordAdmin, SimpleHistoryAdmin)


@pytest.mark.django_db
def test_admin_machine_uid_display(machine):
    record = InspectionFactory(machine=machine)
    admin = ServiceRecordAdmin(ServiceRecord, site)
    assert admin.machine_uid(record) == machine.uid


@pytest.mark.django_db
def test_admin_list_display_has_core_fields():
    admin = ServiceRecordAdmin(ServiceRecord, site)
    expected = {"machine_uid", "performed_date", "record_type", "cost"}
    assert expected.issubset(set(admin.list_display))
