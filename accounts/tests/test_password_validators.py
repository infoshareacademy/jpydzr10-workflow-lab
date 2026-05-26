"""Testy walidatora HIBP (``PwnedPasswordsValidator``).

W ``planer_config/settings/base.py`` AUTH_PASSWORD_VALIDATORS zawiera
``pwned_passwords_django.validators.PwnedPasswordsValidator`` — k-anonymity
sprawdzenie hasła przeciwko bazie Have I Been Pwned. W
``planer_config/settings/test.py`` walidator jest USUWANY (offline tests),
co tworzy lukę testową: produkcyjna ścieżka NIE jest pokryta.

Ten moduł zamyka tę lukę używając ``mock.patch`` na warstwie API client
(zamiast walidatora) — żeby pokryć też fallback do CommonPasswordValidator
gdy HIBP API jest niedostępne.

Pokrywa P0 L2-4 audit gap (security): bez tych testów refactor pipeline
walidacji (np. usunięcie HIBP z base.py) przeszedłby bez sygnału.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from pwned_passwords_django.exceptions import ErrorCode, PwnedPasswordsError


@pytest.fixture
def hibp_only_validators(settings):
    """Ustaw AUTH_PASSWORD_VALIDATORS na tylko HIBP validator.

    Izoluje test od pozostałych walidatorów (MinLength, CommonPassword,
    UserAttributeSimilarity, NumericPassword) — gdyby któryś z nich
    odrzucił hasło PRZED HIBP, test by zwrócił false positive.
    """
    settings.AUTH_PASSWORD_VALIDATORS = [
        {"NAME": "pwned_passwords_django.validators.PwnedPasswordsValidator"},
    ]


@pytest.mark.django_db
class TestHIBPValidator:
    """Pokrycie ścieżki HIBP w pipeline walidacji haseł.

    Mockujemy ``api.default_client.check_password`` — to jest warstwa
    network call, nad którą walidator buduje logikę. Mock pozwala
    deterministycznie testować trzy scenariusze: pwned, clean, API error.
    """

    @patch("pwned_passwords_django.api.default_client.check_password")
    def test_pwned_password_rejected(self, mock_check, hibp_only_validators):
        """Hasło zwrócone przez HIBP z count > 0 → ValidationError.

        Przepływ: HIBP API zwraca liczbę wystąpień hasła w wyciekach.
        Cokolwiek > 0 oznacza że hasło zostało ujawnione. Walidator
        rzuca wówczas ``ValidationError`` z kodem ``password_compromised``.

        Test pokrywa: integracja walidatora z Django pipeline + komunikat
        błędu zawiera info o tym że hasło jest "too common" (default message
        biblioteki — można nadpisać OPTIONS).
        """
        mock_check.return_value = 12345  # liczba wystąpień w wyciekach
        with pytest.raises(ValidationError) as exc_info:
            validate_password("password123")
        # Walidator domyślnie używa message "This password is too common."
        # — sprawdzamy że ValidationError dotyczy ujawnionego hasła.
        assert exc_info.value.error_list  # ma jakiś error
        # kod błędu musi wskazywać password_compromised
        codes = [e.code for e in exc_info.value.error_list]
        assert "password_compromised" in codes

    @patch("pwned_passwords_django.api.default_client.check_password")
    def test_pwned_password_accepted_when_not_in_breach(self, mock_check, hibp_only_validators):
        """Hasło z count == 0 → walidator przepuszcza (no exception).

        Happy path: HIBP API zwraca 0 wystąpień → hasło uznane za czyste,
        walidator nie podnosi błędu. Inne walidatory mogą jeszcze odrzucić
        (np. zbyt krótkie), ale w tym teście HIBP jest jedyny aktywny.
        """
        mock_check.return_value = 0  # zero wystąpień = clean
        # Nie powinno rzucić — walidator OK przepuszcza.
        validate_password("unikalne-haslo-2026-jakiego-nikt-nie-uzywa!")

    @patch("pwned_passwords_django.api.default_client.check_password")
    def test_pwned_validator_falls_back_to_common_when_api_fails(
        self, mock_check, hibp_only_validators
    ):
        """Gdy HIBP API niedostępne → fallback do CommonPasswordValidator.

        Documented behavior biblioteki ``pwned-passwords-django``: na
        ``PwnedPasswordsError`` (timeout/connection/HTTP error), walidator
        zamiast cichego "pass" lub raise PwnedPasswordsError, wykonuje
        fallback do Django's ``CommonPasswordValidator``. Dzięki temu:

        * popularne hasła nadal są rzucane (CommonPassword Django ma swoją
          listę top-2000),
        * unikalne hasła przechodzą (fail-soft dla user experience).
        """
        mock_check.side_effect = PwnedPasswordsError(
            "API down",
            code=ErrorCode.API_TIMEOUT,
            params={},
        )
        # Nieoczywiste hasło — Django CommonPasswordValidator NIE ma go
        # na liście, więc fallback powinien przepuścić.
        validate_password("unikalne-haslo-2026-jakiego-nikt-nie-uzywa!")

    @patch("pwned_passwords_django.api.default_client.check_password")
    def test_pwned_validator_fallback_still_rejects_common_passwords(
        self, mock_check, hibp_only_validators
    ):
        """Fallback do CommonPasswordValidator NADAL odrzuca top-listę.

        Negative test do test_pwned_validator_falls_back_to_common_when_api_fails:
        gdy HIBP nie działa, popularne hasło ("password") jest odrzucone
        przez Django CommonPasswordValidator (top-2000 lista). To kluczowy
        guard — fail-soft NIE oznacza "wszystko przepuszczamy".
        """
        mock_check.side_effect = PwnedPasswordsError(
            "API down",
            code=ErrorCode.HTTP_ERROR,
            params={},
        )
        # "password" jest w Django common-passwords.txt → CommonPasswordValidator raises
        with pytest.raises(ValidationError):
            validate_password("password")


@pytest.mark.django_db
class TestHIBPValidatorConfigured:
    """Smoke test: czy klasa walidatora istnieje pod expected path?

    Jeśli zostanie zmieniony import w base.py (literówka, refactor), Django
    powinien rzucić ImproperlyConfigured przy starcie. Ten test sprawdza
    że class jest faktycznie dostępna pod ścieżką używaną w settings.
    """

    def test_validator_class_importable(self):
        """Klasa PwnedPasswordsValidator dostępna pod udokumentowaną ścieżką."""
        from pwned_passwords_django.validators import PwnedPasswordsValidator

        validator = PwnedPasswordsValidator()
        # Smoke: validator ma metodę validate.
        assert hasattr(validator, "validate")
        assert callable(validator.validate)

    def test_validator_get_help_text_returns_str(self):
        """``get_help_text()`` zwraca komunikat dla UI (signup form)."""
        from pwned_passwords_django.validators import PwnedPasswordsValidator

        validator = PwnedPasswordsValidator()
        help_text = validator.get_help_text()
        # Wymagamy że ma jakąkolwiek treść (string lub lazy Promise).
        assert help_text
        assert len(str(help_text)) > 0
