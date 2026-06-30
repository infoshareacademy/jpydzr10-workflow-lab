"""Testy agenta głosowego (część testowalna: stan, caller-ID, dyspozytor).

Żywe gniazdo WS (Gemini Live) jest bramkowane akcjami autora i NIE jest tu
testowane — sprawdzamy maszynę stanów, rozpoznanie dzwoniącego po numerze oraz
reużycie reguł uprawnień (admin pisze, montażysta/gość tylko czytają).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model

from accounts.models import EmployeeProfile
from chatbot.voice_consumer import (
    build_user_perms_summary,
    confirm_pending,
    propose_or_execute,
)
from chatbot.voice_session import VoiceCallSession, VoiceState
from machines.models import Machine

User = get_user_model()

pytestmark = pytest.mark.django_db


def _role_user(username, function, phone):
    user = User.objects.create_user(username=username, password="x")
    profile = user.profile
    profile.function = function
    profile.phone = phone
    profile.save(update_fields=["function", "phone", "updated_at"])
    return User.objects.get(pk=user.pk)


# -----------------------------------------------------------------------------
# Maszyna stanów VoiceCallSession
# -----------------------------------------------------------------------------


class TestVoiceSession:
    def test_guest_cannot_write(self):
        s = VoiceCallSession(call_sid="CA1", user=None)
        assert s.is_guest
        assert not s.can_write

    def test_propose_confirm_cycle(self):
        s = VoiceCallSession(call_sid="CA2", user=object())
        s.propose("create_reservation", {"machine_uid": "KOP-001"})
        assert s.has_pending()
        assert s.state is VoiceState.AWAITING_CONFIRMATION
        action, params = s.confirm()
        assert action == "create_reservation"
        assert params == {"machine_uid": "KOP-001"}
        assert not s.has_pending()
        assert s.state is VoiceState.IDLE

    def test_cancel_clears_pending(self):
        s = VoiceCallSession(call_sid="CA3", user=object())
        s.propose("cancel_reservation", {"reservation_id": 5})
        s.cancel()
        assert not s.has_pending()

    def test_confirm_without_pending_raises(self):
        s = VoiceCallSession(call_sid="CA4", user=object())
        with pytest.raises(ValueError, match="oczekując"):
            s.confirm()


# -----------------------------------------------------------------------------
# Webhook caller-ID
# -----------------------------------------------------------------------------


class TestVoiceWebhook:
    def test_known_caller_resolved_to_user(self, client):
        user = _role_user("dzwoniacy", EmployeeProfile.Function.KIEROWNIK, "+48600000011")
        response = client.post("/voice/incoming/", {"From": "+48 600 000 011", "CallSid": "CA9"})
        assert response.status_code == 200
        assert response["Content-Type"] == "text/xml"
        body = response.content.decode("utf-8")
        assert "ConversationRelay" in body
        assert f'value="{user.pk}"' in body

    def test_unknown_caller_is_guest(self, client):
        response = client.post("/voice/incoming/", {"From": "+48999999999", "CallSid": "CA8"})
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert 'value="guest"' in body

    def test_known_caller_twiml_has_required_relay_params(self, client):
        """TwiML musi zawierać komplet parametrów ConversationRelay (PL, dostawcy
        STT/TTS) — niekompletny TwiML zerwałby integrację z Twilio."""
        _role_user("relayuser", EmployeeProfile.Function.KIEROWNIK, "+48600000044")
        response = client.post("/voice/incoming/", {"From": "+48600000044", "CallSid": "CA9b"})
        body = response.content.decode("utf-8")
        assert 'language="pl-PL"' in body
        assert 'ttsProvider="Google"' in body
        assert 'transcriptionProvider="Google"' in body
        assert 'dtmfDetection="true"' in body
        assert 'interruptible="any"' in body

    def test_inactive_user_is_guest(self, client):
        """Dezaktywowane konto User → dostęp gościa (nie ujawniamy tożsamości)."""
        user = _role_user("inactive_user", EmployeeProfile.Function.KIEROWNIK, "+48600000055")
        user.is_active = False
        user.save(update_fields=["is_active"])
        response = client.post("/voice/incoming/", {"From": "+48600000055", "CallSid": "CA21"})
        assert 'value="guest"' in response.content.decode("utf-8")

    def test_inactive_profile_is_guest(self, client):
        """Profil z is_active_employee=False → gość."""
        user = _role_user("inactive_prof", EmployeeProfile.Function.KIEROWNIK, "+48600000033")
        user.profile.is_active_employee = False
        user.profile.save(update_fields=["is_active_employee", "updated_at"])
        response = client.post("/voice/incoming/", {"From": "+48600000033", "CallSid": "CA22"})
        assert 'value="guest"' in response.content.decode("utf-8")

    def test_anonymized_profile_is_guest(self, client):
        """Profil zanonimizowany (GDPR) → gość."""
        user = _role_user("anon_prof", EmployeeProfile.Function.KIEROWNIK, "+48600000022")
        user.profile.is_anonymized = True
        user.profile.save(update_fields=["is_anonymized", "updated_at"])
        response = client.post("/voice/incoming/", {"From": "+48600000022", "CallSid": "CA23"})
        assert 'value="guest"' in response.content.decode("utf-8")

    def test_raw_digits_unknown_number_falls_back_to_guest(self, client):
        """Caller-ID jako same cyfry (bez '+') jest normalizowany do '+<cyfry>';
        gdy nie pasuje do żadnego profilu → gość (brak wycieku tożsamości)."""
        response = client.post("/voice/incoming/", {"From": "600000999", "CallSid": "CA24"})
        assert response.status_code == 200
        assert 'value="guest"' in response.content.decode("utf-8")

    def test_invalid_signature_rejected_when_token_set(self, client, settings):
        """Gdy skonfigurowano TWILIO_AUTH_TOKEN, błędny podpis → 403."""
        settings.TWILIO_AUTH_TOKEN = "test-token-abc"
        response = client.post(
            "/voice/incoming/",
            {"From": "+48600000011", "CallSid": "CA25"},
            HTTP_X_TWILIO_SIGNATURE="definitely-wrong-signature",
        )
        assert response.status_code == 403


# -----------------------------------------------------------------------------
# Dyspozytor propozycja → potwierdzenie (reużycie uprawnień)
# -----------------------------------------------------------------------------


class TestVoiceDispatch:
    def test_guest_write_refused(self):
        s = VoiceCallSession(call_sid="CA10", user=None)
        result = propose_or_execute(s, "create_reservation", {})
        assert "gość" in result.lower() or "gosc" in result.lower()
        assert not s.has_pending()

    def test_montazysta_write_refused(self):
        mont = _role_user("mont_voice", EmployeeProfile.Function.MONTAZYSTA, "+48600000099")
        s = VoiceCallSession(call_sid="CA11", user=mont)
        result = propose_or_execute(s, "create_reservation", {})
        assert "uprawnie" in result.lower()
        assert not s.has_pending()

    def test_admin_write_proposes_confirmation(self):
        admin = User.objects.create_superuser("adminvoice", "a@a.test", "x")
        s = VoiceCallSession(call_sid="CA12", user=admin)
        params = {"machine_uid": "KOP-001", "person": "Jan"}
        result = propose_or_execute(s, "create_reservation", params)
        assert "potwierdzasz" in result.lower()
        assert s.has_pending()
        # Akcja i parametry MUSZĄ trafić do stanu sesji nienaruszone — inaczej
        # potwierdzenie wykonałoby coś innego niż zaproponowano.
        assert s.pending_action == "create_reservation"
        assert s.pending_params == params

    def test_kierownik_write_proposes_confirmation(self):
        """Środkowy poziom RBAC: KIEROWNIK ma add_reservation → SKŁADA wnioski
        (create), ale NIE zatwierdza/anuluje (change_reservation = magazynier/
        admin). Granica: gość < montażysta < kierownik < magazynier."""
        kier = _role_user("kier_voice", EmployeeProfile.Function.KIEROWNIK, "+48600000077")
        assert kier.has_perm("reservations.add_reservation")
        assert not kier.has_perm("reservations.change_reservation")
        # Składanie wniosku (add_reservation) — proponuje zapis jak admin.
        s = VoiceCallSession(call_sid="CA12b", user=kier)
        result = propose_or_execute(s, "create_reservation", {"machine_uid": "KOP-001"})
        assert "potwierdzasz" in result.lower()
        assert s.pending_action == "create_reservation"
        # Akcja wymagająca change_reservation (anulowanie) — kierownik NIE może.
        s2 = VoiceCallSession(call_sid="CA12c", user=kier)
        result2 = propose_or_execute(s2, "cancel_reservation", {"reservation_id": 1})
        assert "uprawnień" in result2.lower()
        assert not s2.has_pending()

    def test_confirm_executes_create_reservation(self):
        admin = User.objects.create_superuser("adminexec", "a@a.test", "x")
        machine = Machine.objects.create(
            uid="KOP-V01",
            name="Koparka voice",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        start = date.today() + timedelta(days=4)
        end = start + timedelta(days=3)
        params = {
            "machine_uid": machine.uid,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "person": "Jan Kowalski",
            "address": "ul. Polna 5, Kraków",
            "responsible_person": "Anna Nowak",
        }
        s = VoiceCallSession(call_sid="CA13", user=admin)
        propose_or_execute(s, "create_reservation", params)
        result = confirm_pending(s)
        assert "utworzona" in result.lower()
        from reservations.models import Reservation

        reservation = Reservation.objects.latest("pk")
        # Weryfikujemy że WSZYSTKIE pola trafiły z params do rekordu — nie tylko
        # że "coś" się utworzyło (tautologia stringa "utworzona").
        assert reservation.created_by == admin
        assert reservation.machine == machine
        assert reservation.start_date == start
        assert reservation.end_date == end
        assert reservation.person == "Jan Kowalski"
        assert reservation.address == "ul. Polna 5, Kraków"
        assert reservation.responsible_person == "Anna Nowak"
        # Po wykonaniu stan wraca do IDLE (brak wiszącej akcji).
        assert not s.has_pending()

    def test_confirm_fails_if_perms_revoked(self):
        """Defense-in-depth re-authoryzacja: jeśli user straci uprawnienia
        MIĘDZY propozycją a potwierdzeniem, confirm odmawia i NIC nie zapisuje."""
        kier = _role_user("kier_revoke", EmployeeProfile.Function.KIEROWNIK, "+48600000066")
        machine = Machine.objects.create(
            uid="KOP-V02",
            name="Koparka revoke",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        start = date.today() + timedelta(days=4)
        params = {
            "machine_uid": machine.uid,
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=2)).isoformat(),
            "person": "Ewa Zielona",
            "address": "ul. Leśna 9, Gdańsk",
            "responsible_person": "Piotr Biały",
        }
        s = VoiceCallSession(call_sid="CA14", user=kier)
        propose_or_execute(s, "create_reservation", params)
        assert s.has_pending()

        # Odbieramy uprawnienia (revoke RBAC) i czyścimy cache permissionów
        # przez ponowne pobranie obiektu User z bazy.
        kier.groups.clear()
        from reservations.models import Reservation

        before = Reservation.objects.count()
        s.user = User.objects.get(pk=kier.pk)
        result = confirm_pending(s)

        assert "uprawnie" in result.lower()
        assert Reservation.objects.count() == before  # żaden zapis się nie wykonał

    def test_read_action_executes_immediately(self):
        """Akcja odczytu wykonuje się od razu — bez wchodzenia w stan
        oczekiwania na potwierdzenie."""
        admin = User.objects.create_superuser("adminread", "a@a.test", "x")
        Machine.objects.create(
            uid="KOP-R01",
            name="Koparka read",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        s = VoiceCallSession(call_sid="CA15", user=admin)
        result = propose_or_execute(s, "get_machine_status", {"uid": "KOP-R01"})
        assert not s.has_pending()
        assert "potwierdzasz" not in result.lower()
        # Realne dane w odpowiedzi (JSON modelu MachineStatusResult).
        assert '"found":true' in result.replace(" ", "")
        assert "KOP-R01" in result

    def test_guest_can_read(self):
        """Gość (user=None) MA dostęp do odczytu — nie dostaje 'sesja wygasła'."""
        Machine.objects.create(
            uid="KOP-G01",
            name="Koparka guest",
            machine_type=Machine.Type.KOPARKA,
            status=Machine.Status.W_MAGAZYNIE,
        )
        s = VoiceCallSession(call_sid="CA16", user=None)
        assert s.is_guest
        result = propose_or_execute(s, "get_machine_status", {"uid": "KOP-G01"})
        assert not s.has_pending()
        assert "KOP-G01" in result
        assert '"found":true' in result.replace(" ", "")
        # Brak komunikatów o wygasłej/niezalogowanej sesji na ścieżce odczytu.
        assert "sesja" not in result.lower()

    def test_guest_write_still_refused_via_dispatch(self):
        """Kontrola bezpieczeństwa: poluzowanie odczytu dla gościa NIE otwiera
        ścieżki zapisu — akcja zapisująca dalej odrzucana."""
        s = VoiceCallSession(call_sid="CA17", user=None)
        result = propose_or_execute(s, "create_reservation", {"machine_uid": "KOP-001"})
        assert "gość" in result.lower() or "gosc" in result.lower()
        assert not s.has_pending()

    def test_unknown_action_rejected(self):
        """Akcja spoza zbiorów READ i WRITE nie jest wykonywana ani zapamiętana."""
        admin = User.objects.create_superuser("adminunk", "a@a.test", "x")
        s = VoiceCallSession(call_sid="CA18", user=admin)
        result = propose_or_execute(s, "drop_database", {})
        assert "rozpoznaj" in result.lower()
        assert not s.has_pending()

    def test_confirm_pending_without_proposal(self):
        """confirm_pending na sesji bez wiszącej akcji zwraca komunikat,
        a nie wyjątek (poziom dyspozytora, nie maszyny stanów)."""
        admin = User.objects.create_superuser("adminnp", "a@a.test", "x")
        s = VoiceCallSession(call_sid="CA19", user=admin)
        assert not s.has_pending()
        result = confirm_pending(s)
        assert "oczekując" in result.lower()

    def test_propose_overwrites_pending(self):
        """Druga propozycja nadpisuje pierwszą (udokumentowane zachowanie
        sesji głosowej — ostatnia propozycja wygrywa)."""
        admin = User.objects.create_superuser("adminov", "a@a.test", "x")
        s = VoiceCallSession(call_sid="CA20", user=admin)
        propose_or_execute(s, "create_reservation", {"machine_uid": "KOP-001"})
        propose_or_execute(s, "cancel_reservation", {"reservation_id": 7})
        assert s.has_pending()
        assert s.pending_action == "cancel_reservation"
        assert s.pending_params == {"reservation_id": 7}

    def test_perms_summary_variants(self):
        admin = User.objects.create_superuser("adminsum", "a@a.test", "x")
        mont = _role_user("montsum", EmployeeProfile.Function.MONTAZYSTA, "+48600000088")
        admin_summary = build_user_perms_summary(admin)
        assert "zapisujące" in admin_summary
        # Superuser ma WSZYSTKIE write actions — konkretne nazwy MUSZĄ się pojawić
        # (nie wystarczy samo hardcoded słowo "zapisujące").
        assert "create_reservation" in admin_summary
        assert "cancel_reservation" in admin_summary
        assert "gości" in build_user_perms_summary(None).lower()
        # Montażysta nie ma żadnych write perms → komunikat o samym odczycie.
        mont_summary = build_user_perms_summary(mont)
        assert "odczyt" in mont_summary.lower()
        assert "create_reservation" not in mont_summary
