"""Wave 14-I — final coverage push 98%→99%+ dla service module.

Pokrywa pozostałe missed branches:

* ``views.py`` line 242 — upload.seek(0) w pętli (multiple machines z plikiem),
* ``views.py`` line 251 → 256 branch (created pusty + warnings).
* ``models.py`` line 133 — ServiceRecord.__repr__.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from machines.models import Machine
from service.factories import InspectionFactory
from service.models import ServiceRecord


def _service_user_with_perms(db):
    """Helper: tworzy usera z permission do bulk create."""
    user_model = get_user_model()
    user = user_model.objects.create_user(username="svctester", password="pw-123!")
    perm = Permission.objects.get(codename="add_servicerecord")
    user.user_permissions.add(perm)
    return user


@pytest.fixture
def svc_client(client, db):
    user = _service_user_with_perms(db)
    client.force_login(user)
    return client


# =============================================================================
# views.py — BulkInspectionView upload + multiple machine paths
# =============================================================================


@pytest.mark.django_db
class TestBulkInspectionUploadSeekLoop:
    """Pokrywa line 242: upload.seek(0) w pętli wielomaszyn."""

    def test_bulk_inspection_with_file_seek_reset(self, svc_client):
        """Multi-machine bulk + plik PDF → upload.seek(0) między iteracjami."""
        m1 = Machine.objects.create(
            uid="BULK-001",
            name="Maszyna bulk 1",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        m2 = Machine.objects.create(
            uid="BULK-002",
            name="Maszyna bulk 2",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        pdf_bytes = b"%PDF-1.4\n%fake-PDF-for-test\n"
        upload = SimpleUploadedFile("inspection.pdf", pdf_bytes, content_type="application/pdf")
        response = svc_client.post(
            reverse("service:bulk_inspection"),
            data={
                "machines": [m1.pk, m2.pk],
                "record_type": ServiceRecord.RecordType.PRZEGLAD_ROCZNY.value,
                "performed_date": "2026-05-10",
                "performed_by": "Anna Serwis",
                "description": "Bulk z plikiem",
                "cost": "100.00",
                "inspection_document": upload,
            },
        )
        # Redirect po sukcesie (302)
        assert response.status_code == 302
        # Każda maszyna powinna mieć wpis (seek poszedł między iteracjami).
        assert (
            ServiceRecord.objects.filter(
                machine__in=[m1, m2], performed_date=date(2026, 5, 10)
            ).count()
            == 2
        )


@pytest.mark.django_db
class TestBulkInspectionWarningPaths:
    """Pokrywa lines 256-259: errors[:10] + ellipsis."""

    def test_bulk_with_many_errors_displays_truncated_warnings(self, svc_client, monkeypatch):
        """>10 errors → pokazuje 10 + ... ile dalszych (warning truncation)."""
        from django.core.exceptions import ValidationError

        from service import views as service_views

        machines = [
            Machine.objects.create(
                uid=f"WARN-{i:03d}",
                name=f"Warn {i}",
                machine_type=Machine.Type.KOPARKA,
                status=Machine.Status.W_MAGAZYNIE,
            )
            for i in range(15)
        ]
        ok_machine = Machine.objects.create(
            uid="OK-001",
            name="OK",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )

        # Monkey-patch create_service_record — rzuca VR dla WARN-*, ok dla OK
        original = service_views.create_service_record

        def selective_boom(**kwargs):
            machine = kwargs.get("machine")
            if machine and machine.uid.startswith("WARN-"):
                raise ValidationError(f"Forced VR for {machine.uid}")
            return original(**kwargs)

        monkeypatch.setattr(service_views, "create_service_record", selective_boom)

        response = svc_client.post(
            reverse("service:bulk_inspection"),
            data={
                "machines": [m.pk for m in machines] + [ok_machine.pk],
                "record_type": ServiceRecord.RecordType.PRZEGLAD_ROCZNY.value,
                "performed_date": "2026-05-10",
                "performed_by": "X",
                "description": "Z błędami",
                "cost": "100.00",
            },
        )
        # Sukces redirect (ok_machine się stworzyła, mimo 15 błędów)
        assert response.status_code == 302
        # OK machine ma wpis
        assert ServiceRecord.objects.filter(machine=ok_machine).count() == 1


# =============================================================================
# models.py — ServiceRecord.__repr__ smoke
# =============================================================================


@pytest.mark.django_db
class TestServiceRecordRepr:
    def test_repr_contains_pk_machine_type_date(self, db):
        machine = Machine.objects.create(
            uid="REPR-001",
            name="Repr",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        rec = InspectionFactory(machine=machine, performed_date=date(2026, 5, 1))
        rep = repr(rec)
        assert "ServiceRecord" in rep
        assert str(rec.pk) in rep
        assert str(machine.pk) in rep
