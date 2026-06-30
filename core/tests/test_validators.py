"""Testy walidatorów uploadu plików."""

from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from core.validators import (
    MAX_DOCUMENT_SIZE,
    MAX_IMAGE_SIZE,
    validate_document_upload,
    validate_image_upload,
)


class _FakeFile:
    """Minimalny obiekt naśladujący FileField value (size + name)."""

    def __init__(self, name: str, size: int):
        self.name = name
        self.size = size


def _make_image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (10, 10)) -> bytes:
    """Tworzy bajty prawdziwego (krótkiego) obrazka w wybranym formacie."""
    buf = BytesIO()
    Image.new("RGB", size, color="red").save(buf, format=fmt)
    return buf.getvalue()


def test_validate_image_upload_accepts_valid_jpg():
    """Małe JPG przechodzi bez wyjątku."""
    validate_image_upload(_FakeFile("foto.jpg", 1024))


def test_validate_image_upload_accepts_png_and_webp():
    """PNG i WebP są dozwolone."""
    validate_image_upload(_FakeFile("foto.png", 1024))
    validate_image_upload(_FakeFile("foto.webp", 1024))


def test_validate_image_upload_rejects_oversized():
    """Zdjęcie > 10 MB powinno rzucić ValidationError."""
    with pytest.raises(ValidationError, match="MB"):
        validate_image_upload(_FakeFile("foto.jpg", MAX_IMAGE_SIZE + 1))


def test_validate_image_upload_rejects_unknown_extension():
    """Pliki innego typu (np. .pdf) są odrzucane."""
    with pytest.raises(ValidationError, match="rozszerzenie"):
        validate_image_upload(_FakeFile("foto.pdf", 1024))


def test_validate_document_upload_accepts_small_pdf():
    """Mały PDF przechodzi bez błędu (FakeFile bez .seek pomija magic-bytes)."""
    validate_document_upload(_FakeFile("raport.pdf", 2048))


def test_validate_document_upload_rejects_non_pdf():
    """Plik nie-PDF jest odrzucany."""
    with pytest.raises(ValidationError, match="PDF"):
        validate_document_upload(_FakeFile("raport.docx", 2048))


def test_validate_document_upload_rejects_oversized():
    """PDF > 20 MB jest odrzucany."""
    with pytest.raises(ValidationError, match="MB"):
        validate_document_upload(_FakeFile("raport.pdf", MAX_DOCUMENT_SIZE + 1))


def test_validate_image_upload_works_with_simple_uploaded_file():
    """Walidator działa z SimpleUploadedFile z prawdziwą zawartością JPG."""
    uploaded = SimpleUploadedFile("test.jpg", _make_image_bytes("JPEG"), content_type="image/jpeg")
    validate_image_upload(uploaded)


def test_validate_image_validator_rejects_fake_image_with_jpg_extension():
    """Plik z rozszerzeniem .jpg ale zawartością ``not-an-image`` jest odrzucony.

    Krytyczne: blokuje upload ``mal.exe`` przemianowanego na ``mal.jpg``.
    """
    uploaded = SimpleUploadedFile("fake.jpg", b"this is not an image", content_type="image/jpeg")
    with pytest.raises(ValidationError, match="nie jest prawidłowym obrazem"):
        validate_image_upload(uploaded)


def test_validate_image_upload_accepts_real_png():
    """Prawdziwy PNG (poprawne magic bytes + struktura) przechodzi walidację."""
    uploaded = SimpleUploadedFile("test.png", _make_image_bytes("PNG"), content_type="image/png")
    validate_image_upload(uploaded)


def test_validate_document_validator_rejects_non_pdf():
    """Plik z rozszerzeniem .pdf ale bez magic bytes ``%PDF-`` jest odrzucony."""
    uploaded = SimpleUploadedFile(
        "fake.pdf", b"PK\x03\x04 not a pdf, looks like zip", content_type="application/pdf"
    )
    with pytest.raises(ValidationError, match="nie jest prawidłowym PDF"):
        validate_document_upload(uploaded)


def test_validate_document_upload_accepts_real_pdf_magic_bytes():
    """SimpleUploadedFile z zawartością zaczynającą się od ``%PDF-`` przechodzi."""
    uploaded = SimpleUploadedFile(
        "real.pdf",
        b"%PDF-1.4\n%fake-but-valid-header\n",
        content_type="application/pdf",
    )
    validate_document_upload(uploaded)


def test_validate_image_upload_catches_decompression_bomb(monkeypatch):
    """Pillow DecompressionBombError → ValidationError (zamiast 500).

    Symulujemy "zip bomb dla obrazów" przez monkeypatch ``Image.open(...).verify()``
    żeby rzucało ``DecompressionBombError``. Bez fixu — exception bąbluje
    poza walidator → Django 500 internal server error. Z fixem — łapiemy
    i zamieniamy na ``ValidationError`` (audyt C2-9 P1).

    Realne triggerowanie wymagałoby pliku 60M+ pixeli (~50 MB JPEG) co jest
    niepraktyczne w teście jednostkowym; monkeypatch jest deterministyczny
    i szybki.
    """

    class _BombingImage:
        def verify(self):
            raise Image.DecompressionBombError("Symulowany 60Mpx obraz")

    monkeypatch.setattr(Image, "open", lambda _value: _BombingImage())

    uploaded = SimpleUploadedFile("bomb.jpg", _make_image_bytes("JPEG"), content_type="image/jpeg")
    with pytest.raises(ValidationError, match=r"zbyt duży|prawidłowym obrazem"):
        validate_image_upload(uploaded)


# =============================================================================
# Wave 12 — OSError branches w _can_seek + _read_magic_bytes
# =============================================================================


class _OSErrorFile:
    """Plik który ma seek/read ale rzucają OSError (np. dysk pełny / zamknięty stream)."""

    def __init__(self, name: str, size: int):
        self.name = name
        self.size = size

    def seek(self, *args, **kwargs):
        raise OSError("Stream is closed")

    def read(self, *args, **kwargs):
        raise OSError("Stream is closed")


def test_can_seek_os_error_returns_false():
    """OSError w seek → _can_seek zwraca False (line 42-43)."""
    from core.validators import _can_seek

    assert _can_seek(_OSErrorFile("x.jpg", 100)) is False


def test_validate_image_upload_skips_verify_when_seek_fails():
    """OSError w seek → walidator early-returns bez weryfikacji content."""
    bad_seek = _OSErrorFile("foto.jpg", 1024)
    # Nie rzuca — rozmiar + ext OK, seek-fail → skip verify
    validate_image_upload(bad_seek)


def test_read_magic_bytes_os_error_returns_none():
    """OSError w seek/read → _read_magic_bytes returns None (line 59-60)."""
    from core.validators import _read_magic_bytes

    assert _read_magic_bytes(_OSErrorFile("x.pdf", 100), 5) is None


def test_validate_document_upload_skips_magic_check_when_read_fails():
    """OSError w read → walidator early-returns (rozmiar+ext OK)."""
    bad_read = _OSErrorFile("doc.pdf", 1024)
    validate_document_upload(bad_read)


# =============================================================================
# Normalizacja i walidacja numerów telefonu (E.164)
# =============================================================================


class TestNormalizePhoneE164:
    """Kontrakt ``normalize_phone_e164`` — patrz docstring funkcji.

    Funkcja CELOWO nie waliduje wyniku (zwraca oczyszczonego kandydata, nie
    ``None`` dla błędnego formatu) — by formularz mógł pokazać błąd, a webhook
    głosowy nie wywracał się na losowym caller-ID. Ścisłe E.164 egzekwuje
    ``EmployeeProfile.save`` / walidator pola.
    """

    def test_empty_and_none_return_none(self):
        from core.validators import normalize_phone_e164

        assert normalize_phone_e164(None) is None
        assert normalize_phone_e164("") is None
        assert normalize_phone_e164("   ") is None

    def test_strips_separators(self):
        from core.validators import normalize_phone_e164

        assert normalize_phone_e164("+48 600 100 200") == "+48600100200"
        assert normalize_phone_e164("+48-600-100-200") == "+48600100200"
        assert normalize_phone_e164("(48) 600.100.200") == "+48600100200"

    def test_prefixes_plus_for_bare_digits(self):
        from core.validators import normalize_phone_e164

        assert normalize_phone_e164("48600100200") == "+48600100200"

    def test_returns_cleaned_candidate_even_if_not_valid_e164(self):
        # Świadomy kontrakt: błędny numer NIE jest zamieniany na None tutaj —
        # to pozwala wyższym warstwom zgłosić czytelny błąd zamiast cicho
        # wyzerować pole.
        from core.validators import normalize_phone_e164

        assert normalize_phone_e164("+0123456789") == "+0123456789"
        assert normalize_phone_e164("abc") == "abc"


class TestIsValidE164:
    def test_accepts_valid_numbers(self):
        from core.validators import is_valid_e164

        assert is_valid_e164("+48600100200")
        assert is_valid_e164("+12025550123")

    def test_rejects_invalid_numbers(self):
        from core.validators import is_valid_e164

        assert not is_valid_e164(None)
        assert not is_valid_e164("")
        assert not is_valid_e164("+0123456789")  # leading 0 po "+"
        assert not is_valid_e164("+1234567")  # za krótki (7 cyfr po +)
        assert not is_valid_e164("+123456789012345678")  # za długi (>15)
        assert not is_valid_e164("48600100200")  # brak "+"
        assert not is_valid_e164("abc")


def test_e164_pattern_matches_migration():
    """Wzorzec E.164 w core.validators == wzorzec w migracji 0005 (DRY guard).

    Regex jest świadomie zduplikowany (migracje muszą być samowystarczalne),
    więc pilnujemy testem, że oba źródła pozostają identyczne — rozjazd
    przepuściłby numery przez jedną warstwę a odrzucił w drugiej.
    """
    import importlib

    from core.validators import E164_PATTERN

    migration = importlib.import_module("accounts.migrations.0005_normalize_phone_e164")
    assert migration._E164_RE.pattern == E164_PATTERN
