"""Testy wymuszenia i przepływu 2FA (TOTP) — django-otp.

Wszystkie testy flipują ``OTP_TESTING_BYPASS=False`` (reszta sufity polega na
domyślnym obejściu z ``settings/test.py``), więc weryfikują REALNE wymuszenie
bez dotykania pozostałych testów logujących przez ``force_login``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.middleware import is_totp_required_for_user
from accounts.models import EmployeeProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _enforce_2fa(settings):
    """Włącza realne wymuszenie 2FA dla całego modułu (reszta sufity je omija)."""
    settings.OTP_TESTING_BYPASS = False
    settings.OTP_ENFORCE_2FA = True


def _make_user(username, function):
    user = User.objects.create_user(username=username, password="secret-pw-123!")
    profile = user.profile
    profile.function = function
    profile.save(update_fields=["function", "updated_at"])
    return user


def _valid_totp(device: TOTPDevice) -> str:
    token = totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)
    return f"{token:0{device.digits}d}"


# -----------------------------------------------------------------------------
# Predykat wymogu
# -----------------------------------------------------------------------------


class TestRequirementPredicate:
    def test_required_roles(self):
        assert is_totp_required_for_user(_make_user("k", EmployeeProfile.Function.KIEROWNIK))
        assert is_totp_required_for_user(_make_user("m", EmployeeProfile.Function.MAGAZYNIER))

    def test_admin_function_required(self):
        # Funkcja ADMIN (NIE flaga is_superuser) jest osobno wymieniona w
        # _TOTP_REQUIRED_FUNCTIONS — user z function=ADMIN, lecz bez is_superuser,
        # musi być objęty wymogiem 2FA. Bez tej asercji usunięcie ADMIN z
        # frozenset przeszłoby niezauważone.
        admin_user = _make_user("adminfn", EmployeeProfile.Function.ADMIN)
        assert not admin_user.is_superuser
        assert is_totp_required_for_user(admin_user)

    def test_montazysta_exempt(self):
        assert not is_totp_required_for_user(_make_user("t", EmployeeProfile.Function.MONTAZYSTA))

    def test_superuser_required(self):
        admin = User.objects.create_superuser("admin", "a@a.test", "secret-pw-123!")
        assert is_totp_required_for_user(admin)

    def test_user_without_profile_not_required(self):
        # Defensywny branch: profile=None → brak wymogu (gość/edge-case po
        # ręcznym usunięciu profilu). NIE może rzucać AttributeError.
        user = _make_user("noprof", EmployeeProfile.Function.MONTAZYSTA)
        user.profile.delete()
        user = User.objects.get(pk=user.pk)
        assert not is_totp_required_for_user(user)

    def test_unauthenticated_not_required(self):
        from django.contrib.auth.models import AnonymousUser

        assert not is_totp_required_for_user(AnonymousUser())


# -----------------------------------------------------------------------------
# Wymuszenie w middleware
# -----------------------------------------------------------------------------


class TestEnforcement:
    def test_required_user_without_device_redirected_to_setup(self, client):
        user = _make_user("kier1", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get("/maszyny/")
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:2fa_setup")

    def test_montazysta_not_redirected(self, client):
        user = _make_user("mont1", EmployeeProfile.Function.MONTAZYSTA)
        client.force_login(user)
        # Profil dostępny bez 2FA — montażysta jest zwolniony.
        response = client.get(reverse("accounts:profile"))
        assert response.status_code == 200

    def test_allow_listed_paths_reachable_without_2fa(self, client):
        user = _make_user("kier2", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        # Sama ścieżka setupu nie może wpadać w pętlę przekierowań.
        response = client.get(reverse("accounts:2fa_setup"))
        assert response.status_code == 200
        # Allow-lista NIE przekierowuje na setup (gdyby tak było, byłaby pętla).
        assert "Location" not in response

    def test_home_reachable_by_required_user_without_2fa(self, client):
        # Strona główna jest specjalnie obsłużona w _is_allowed_path — kierownik
        # bez urządzenia 2FA może ją otworzyć (nie jest spychany do setupu).
        user = _make_user("kierhome", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get(reverse("home"))
        assert response.status_code == 200

    def test_logout_path_reachable_without_2fa(self, client):
        # Inny wpis allow-listy niż sam setup — wylogowanie musi działać nawet
        # gdy 2FA nie zostało jeszcze zweryfikowane (inaczej user utknąłby).
        user = _make_user("kierout", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get("/accounts/logout")
        # /accounts/logout jest na allow-liście → NIE redirect na 2fa_setup.
        assert response.get("Location") != reverse("accounts:2fa_setup")

    def test_required_verified_user_reaches_protected_page(self, client):
        # is_verified()==True (po otp_login) zdejmuje wymuszenie — chroniona
        # strona dostępna bez kolejnego przekierowania na 2FA.
        user = _make_user("kierver", EmployeeProfile.Function.KIEROWNIK)
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        client.force_login(user)
        client.post(reverse("accounts:2fa_verify"), {"token": _valid_totp(device)})
        assert client.get("/maszyny/").status_code == 200

    def test_bypass_flag_disables_enforcement(self, client):
        user = _make_user("kier3", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        with override_settings(OTP_TESTING_BYPASS=True):
            assert client.get("/maszyny/").status_code == 200

    def test_login_suffix_attack_not_allow_listed(self, client):
        # Atak sufiksowy: /accounts/loginEVIL NIE jest trasą logowania, więc NIE
        # może być zwolniony z 2FA. Uprawniony niezweryfikowany user zostaje
        # zepchnięty na setup — gdyby allow-lista używała gołego startswith,
        # przepuściłaby ten URL (i każdy /accounts/login* ).
        user = _make_user("kiersuffix", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get("/accounts/loginEVIL")
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:2fa_setup")

    def test_login_trailing_slash_still_allow_listed(self, client):
        # Realna trasa z ukośnikiem (/accounts/login/) MUSI pozostać dostępna —
        # kotwiczone dopasowanie obejmuje ``trasa + "/"``, więc nie ma pętli.
        user = _make_user("kiertrail", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get("/accounts/login/")
        assert response.get("Location") != reverse("accounts:2fa_setup")

    def test_media_now_behind_2fa(self, client):
        # /media/ zostało USUNIĘTE z allow-listy — przesłane pliki (protokoły
        # przeglądów) to zasób chroniony. Uprawniony niezweryfikowany user jest
        # przekierowany na 2FA zamiast dostać plik.
        user = _make_user("kiermedia", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get("/media/protokoly/tajny.pdf")
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:2fa_setup")


# -----------------------------------------------------------------------------
# Setup → confirm → recovery
# -----------------------------------------------------------------------------


class TestSetupFlow:
    def test_setup_confirms_device_and_issues_recovery_codes(self, client):
        user = _make_user("kier4", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        # GET tworzy niepotwierdzone urządzenie.
        client.get(reverse("accounts:2fa_setup"))
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        response = client.post(reverse("accounts:2fa_setup"), {"token": _valid_totp(device)})
        assert response.status_code == 200
        # Renderowany jest faktycznie szablon kodów zapasowych (nie formularz z błędem).
        assert "accounts/2fa_recovery.html" in {t.name for t in response.templates}
        device.refresh_from_db()
        assert device.confirmed
        # 10 kodów zapasowych powstało i są obecne w sesji do pobrania.
        static_device = StaticDevice.objects.get(user=user, name="recovery")
        assert static_device.token_set.count() == 10
        assert len(client.session["_2fa_recovery_codes"]) == 10
        # Po setupie sesja jest zweryfikowana — chroniona strona dostępna.
        assert client.get("/maszyny/").status_code == 200

    def test_setup_rejects_bad_token(self, client):
        user = _make_user("kier5", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        client.get(reverse("accounts:2fa_setup"))
        response = client.post(reverse("accounts:2fa_setup"), {"token": "000000"}, follow=False)
        assert response.status_code == 200
        assert not TOTPDevice.objects.get(user=user).confirmed
        # Użytkownik widzi komunikat o błędnym kodzie (a nie cichą porażkę).
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("Nieprawidłowy kod" in m for m in messages)
        # Brak kodów zapasowych w sesji — setup się nie powiódł.
        assert "_2fa_recovery_codes" not in client.session

    def test_setup_throttle_shows_distinct_message(self, client, monkeypatch):
        # Gdy verify_is_allowed()==(False, …) (throttling django-otp), user
        # dostaje komunikat o blokadzie, NIE „nieprawidłowy kod" — nawet jeśli
        # wpisał poprawny token.
        user = _make_user("kierthr", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        client.get(reverse("accounts:2fa_setup"))
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        monkeypatch.setattr(TOTPDevice, "verify_is_allowed", lambda self: (False, {}))
        response = client.post(reverse("accounts:2fa_setup"), {"token": _valid_totp(device)})
        assert response.status_code == 200
        device.refresh_from_db()
        assert not device.confirmed  # throttling nie pozwala potwierdzić
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("Zbyt wiele prób" in m for m in messages)
        assert not any("Nieprawidłowy kod" in m for m in messages)

    def test_setup_redirects_to_verify_when_device_confirmed(self, client):
        # Gdy istnieje już potwierdzone urządzenie, GET setup przekierowuje na
        # weryfikację (nie generuje drugiego urządzenia/QR).
        user = _make_user("kiercfm", EmployeeProfile.Function.KIEROWNIK)
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        client.force_login(user)
        response = client.get(reverse("accounts:2fa_setup"))
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:2fa_verify")


# -----------------------------------------------------------------------------
# Verify (TOTP + recovery)
# -----------------------------------------------------------------------------


class TestVerifyFlow:
    def test_verify_with_totp(self, client):
        user = _make_user("kier6", EmployeeProfile.Function.KIEROWNIK)
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        client.force_login(user)
        response = client.post(reverse("accounts:2fa_verify"), {"token": _valid_totp(device)})
        assert response.status_code == 302
        # Cel przekierowania to strona główna (nie dowolny redirect).
        assert response["Location"] == reverse("home")
        assert client.get("/maszyny/").status_code == 200

    def test_verify_with_recovery_code_one_time(self, client):
        user = _make_user("kier7", EmployeeProfile.Function.KIEROWNIK)
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        static_device = StaticDevice.objects.create(user=user, name="recovery")
        static_device.token_set.create(token="zapas1234")
        client.force_login(user)
        # Pierwsze użycie kodu zapasowego — sukces.
        response = client.post(reverse("accounts:2fa_verify"), {"token": "zapas1234"})
        assert response.status_code == 302
        # Drugie użycie tego samego kodu — odrzucone (jednorazowy).
        client.logout()
        client.force_login(user)
        response2 = client.post(reverse("accounts:2fa_verify"), {"token": "zapas1234"})
        assert response2.status_code == 200  # zostaje na stronie weryfikacji

    def test_verify_rejects_invalid_token(self, client):
        # Zły kod (ani TOTP, ani zapasowy) → strona weryfikacji + komunikat.
        user = _make_user("kierbad", EmployeeProfile.Function.KIEROWNIK)
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        client.force_login(user)
        response = client.post(reverse("accounts:2fa_verify"), {"token": "999999"})
        assert response.status_code == 200
        assert client.get("/maszyny/").status_code == 302  # nadal niezweryfikowany
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("Nieprawidłowy kod" in m for m in messages)

    def test_verify_rejects_invalid_recovery_code(self, client):
        # Kod zapasowy spoza zestawu jest odrzucony (zostajemy na weryfikacji).
        user = _make_user("kierrcv", EmployeeProfile.Function.KIEROWNIK)
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        static_device = StaticDevice.objects.create(user=user, name="recovery")
        static_device.token_set.create(token="prawid1234")
        client.force_login(user)
        response = client.post(reverse("accounts:2fa_verify"), {"token": "zlykod9999"})
        assert response.status_code == 200
        # Prawidłowy kod NIE został skonsumowany przez nieudaną próbę.
        assert static_device.token_set.filter(token="prawid1234").exists()

    def test_verify_redirects_to_setup_without_device(self, client):
        # Brak potwierdzonego urządzenia → weryfikacja odsyła do setupu.
        user = _make_user("kiernodev", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        response = client.get(reverse("accounts:2fa_verify"))
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:2fa_setup")

    def test_verify_uses_first_of_multiple_confirmed_devices(self, client):
        # django-otp dopuszcza wiele urządzeń; widok wybiera .first() (najstarsze).
        # Kod z TEGO urządzenia weryfikuje sesję poprawnie.
        user = _make_user("kiermulti", EmployeeProfile.Function.KIEROWNIK)
        first = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        TOTPDevice.objects.create(user=user, name="second", confirmed=True)
        selected = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        assert selected.pk == first.pk
        client.force_login(user)
        response = client.post(reverse("accounts:2fa_verify"), {"token": _valid_totp(selected)})
        assert response.status_code == 302
        assert client.get("/maszyny/").status_code == 200


class TestVerifiedUserBehaviour:
    def test_verified_user_setup_redirects_to_verify(self, client):
        # Zweryfikowany user trafiający na setup jest odsyłany do weryfikacji
        # (ma już potwierdzone urządzenie — nie tworzymy nowego QR).
        user = _make_user("verup", EmployeeProfile.Function.KIEROWNIK)
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        client.force_login(user)
        client.post(reverse("accounts:2fa_verify"), {"token": _valid_totp(device)})
        response = client.get(reverse("accounts:2fa_setup"))
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:2fa_verify")

    def test_verified_user_verify_redirects_home(self, client):
        # GET weryfikacji przez już-zweryfikowanego usera → od razu home.
        user = _make_user("verho", EmployeeProfile.Function.KIEROWNIK)
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)
        client.force_login(user)
        client.post(reverse("accounts:2fa_verify"), {"token": _valid_totp(device)})
        response = client.get(reverse("accounts:2fa_verify"))
        assert response.status_code == 302
        assert response["Location"] == reverse("home")


class TestUnauthenticatedAccess:
    def test_setup_requires_login(self, client):
        response = client.get(reverse("accounts:2fa_setup"))
        assert response.status_code == 302
        assert "/accounts/login" in response["Location"]

    def test_verify_requires_login(self, client):
        response = client.get(reverse("accounts:2fa_verify"))
        assert response.status_code == 302
        assert "/accounts/login" in response["Location"]

    def test_recovery_download_requires_login(self, client):
        response = client.get(reverse("accounts:2fa_recovery_download"))
        assert response.status_code == 302
        assert "/accounts/login" in response["Location"]


class TestRecoveryCodesDownload:
    """Pobranie kodów zapasowych jako pliku TXT (jednorazowo)."""

    def _setup_with_codes(self, client):
        user = _make_user("rcdl", EmployeeProfile.Function.KIEROWNIK)
        client.force_login(user)
        client.get(reverse("accounts:2fa_setup"))
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        client.post(reverse("accounts:2fa_setup"), {"token": _valid_totp(device)})
        return user

    def test_download_returns_txt_with_codes(self, client):
        self._setup_with_codes(client)
        expected_codes = list(client.session["_2fa_recovery_codes"])
        assert len(expected_codes) == 10
        response = client.get(reverse("accounts:2fa_recovery_download"))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")
        assert response["Content-Disposition"] == ('attachment; filename="kody-zapasowe-2fa.txt"')
        body = response.content.decode()
        for code in expected_codes:
            assert code in body

    def test_download_is_one_time_clears_session(self, client):
        self._setup_with_codes(client)
        assert "_2fa_recovery_codes" in client.session
        first = client.get(reverse("accounts:2fa_recovery_download"))
        assert first.status_code == 200
        # Sesyjny klucz został usunięty po pierwszym pobraniu.
        assert "_2fa_recovery_codes" not in client.session
        # Drugie pobranie → redirect na home (brak kodów w sesji).
        second = client.get(reverse("accounts:2fa_recovery_download"))
        assert second.status_code == 302
        assert second["Location"] == reverse("home")

    def test_download_redirects_when_no_codes_in_session(self, client):
        # Zalogowany user bez kodów w sesji (nie przeszedł setupu) → home.
        user = _make_user("rcdlnone", EmployeeProfile.Function.MONTAZYSTA)
        client.force_login(user)
        response = client.get(reverse("accounts:2fa_recovery_download"))
        assert response.status_code == 302
        assert response["Location"] == reverse("home")
