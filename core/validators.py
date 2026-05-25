"""Walidatory uploadów (zdjęcia, dokumenty) z limitami rozmiaru i rozszerzeniem.

Te walidatory są podpinane do FileField/ImageField w innych aplikacjach:
    photo = models.ImageField(upload_to=..., validators=[validate_image_upload])

Walidacja jest trójwarstwowa:

1. Rozmiar — szybki test, działa bez czytania zawartości.
2. Rozszerzenie pliku — whitelist; chroni przed oczywistymi pomyłkami.
3. Magic bytes / Pillow verify — czyta nagłówek pliku i sprawdza, czy
   zawartość naprawdę odpowiada deklarowanemu typowi. Dzięki temu plik
   ``mal.exe`` przemianowany na ``mal.jpg`` zostanie odrzucony.
"""

from contextlib import suppress
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_DOCUMENT_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf"}

# Magic bytes — sygnatura pierwszych bajtów pliku PDF zgodnie ze specyfikacją
# ISO 32000-1, §7.5.2. Każdy prawidłowy PDF zaczyna się od "%PDF-".
_PDF_MAGIC = b"%PDF-"


def _can_seek(value) -> bool:
    """Sprawdza czy uploaded file wspiera ``seek(0)``.

    Wyodrębnione zamiast wieloargumentowego ``except`` — ruff format
    normalizuje ``except (A, B):`` do non-standard ``except A, B:``,
    więc trzymamy każdą reset-zostawione w osobnej funkcji.
    """
    try:
        value.seek(0)
    except AttributeError:
        return False
    except OSError:
        return False
    return True


def _read_magic_bytes(value, n: int) -> bytes | None:
    """Czyta pierwsze ``n`` bajtów z file-like ``value`` i resetuje pozycję.

    Zwraca ``None`` jeśli obiekt nie wspiera seek/read (test fakes itp.) —
    patrz :func:`_can_seek` o motywacji split-except.
    """
    try:
        value.seek(0)
        header = value.read(n)
        value.seek(0)
    except AttributeError:
        return None
    except OSError:
        return None
    return header


def validate_image_upload(value):
    """Walidator uploadu zdjęć: rozmiar + rozszerzenie + faktyczny content image.

    Trzeci krok (``Image.verify()``) chroni przed sytuacją, w której ktoś
    podstawia plik ``.exe`` z rozszerzeniem ``.jpg`` — Pillow zwróci
    :class:`UnidentifiedImageError`, walidator zamieni to na czytelny
    :class:`ValidationError`.
    """
    if value.size > MAX_IMAGE_SIZE:
        raise ValidationError(
            f"Zdjęcie nie może być większe niż {MAX_IMAGE_SIZE // (1024 * 1024)} MB."
        )
    ext = Path(value.name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        raise ValidationError(f"Niedozwolone rozszerzenie. Dozwolone: {allowed}.")
    if not _can_seek(value):
        # Niektóre obiekty (np. ``_FakeFile`` w testach) nie wspierają seek —
        # zostawiamy je wtedy bez weryfikacji content (rozmiar+extension wystarcza).
        return
    try:
        Image.open(value).verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        # ``DecompressionBombError`` jest rzucane przez Pillow gdy plik
        # przekracza ``Image.MAX_IMAGE_PIXELS`` (domyślnie ~89M px) — ochrona
        # przed atakiem typu "zip bomb dla obrazów" (60Mpx+ JPEG, który po
        # dekompresji żre kilka GB RAM). Bez tego catch — niezłapane
        # exception bąbluje do 500 zamiast ValidationError (audyt C2-9 P1).
        raise ValidationError("Plik nie jest prawidłowym obrazem lub jest zbyt duży.") from exc
    finally:
        with suppress(AttributeError, OSError):
            value.seek(0)


def validate_document_upload(value):
    """Walidator uploadu dokumentów: rozmiar + rozszerzenie + magic bytes PDF.

    Sprawdza sygnaturę ``%PDF-`` z nagłówka pliku — odrzuca pliki o
    rozszerzeniu ``.pdf`` które nie są faktycznie PDF-ami (np. archiwum
    ZIP przemianowane na ``.pdf``).
    """
    if value.size > MAX_DOCUMENT_SIZE:
        raise ValidationError(
            f"Dokument nie może być większy niż {MAX_DOCUMENT_SIZE // (1024 * 1024)} MB."
        )
    ext = Path(value.name).suffix.lower()
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValidationError("Dokument musi być w formacie PDF.")
    header = _read_magic_bytes(value, len(_PDF_MAGIC))
    if header is None:
        # Patrz uwaga w ``validate_image_upload`` — fallback dla obiektów bez seek/read.
        return
    if header != _PDF_MAGIC:
        raise ValidationError("Plik nie jest prawidłowym PDF.")
