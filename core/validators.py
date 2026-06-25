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

import re
from contextlib import suppress
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from PIL import Image, UnidentifiedImageError

# Numer telefonu w formacie E.164: znak "+" + cyfra 1-9 + 7-14 dalszych cyfr
# (łącznie 8-15 cyfr po "+"). Pozwala na międzynarodowe numery służbowe i jest
# wykorzystywany m.in. do identyfikacji dzwoniącego (caller-ID) w module głosowym.
#
# Ten sam wzorzec jest CELOWO zduplikowany w migracji
# ``accounts.0005_normalize_phone_e164`` (``_E164_RE``) — migracje muszą być
# samowystarczalne (frozen w czasie), więc nie importują z tego modułu. Zmiana
# wzorca wymaga aktualizacji obu miejsc; test ``test_e164_pattern_matches_migration``
# pilnuje, że pozostają zgodne.
E164_PATTERN = r"^\+[1-9]\d{7,14}$"
E164_RE = re.compile(E164_PATTERN)
phone_e164_validator = RegexValidator(
    regex=E164_PATTERN,
    message="Numer telefonu musi być w formacie międzynarodowym, np. +48123456789.",
)

# Znaki separujące usuwane przy normalizacji numeru (spacje, myślniki, nawiasy, kropki) —
# użytkownik może wpisać "+48 600 100 200", a my przechowujemy ścisłe E.164.
_PHONE_SEPARATORS_RE = re.compile(r"[\s\-().]")


def normalize_phone_e164(raw: str | None) -> str | None:
    """Sprowadza numer do postaci kandydata E.164 (bez separatorów) lub ``None``.

    KONTRAKT (świadomie nie-walidujący — patrz uzasadnienie niżej):

    * puste/``None`` → ``None`` (sentinel braku numeru, wymagany przez UNIQUE na
      polu telefonu),
    * cokolwiek innego → oczyszczony string z separatorów; jeśli to same cyfry
      bez ``+``, dostawiamy ``+`` (best-effort, zakłada że to już numer z
      kierunkowym).

    Wynik NIE jest sprawdzany pod kątem zgodności z :data:`E164_RE`. To celowe:

    * formularze (``accounts.forms._clean_phone_field``) potrzebują *oczyszczonej
      ale potencjalnie błędnej* wartości, by przepuścić ją przez
      :data:`phone_e164_validator` i pokazać użytkownikowi czytelny błąd —
      gdyby normalizacja zwracała ``None`` dla błędnego numeru, formularz cicho
      wyczyściłby pole zamiast zgłosić błąd;
    * webhook głosowy (``chatbot.voice_views.voice_incoming``) podaje dowolny
      caller-ID — funkcja musi zwrócić wartość (a nie rzucić), by
      ``user_for_phone`` mogło zwrócić gościa dla nieznanego numeru.

    Wymuszenie ścisłego E.164 odbywa się w warstwie zapisu
    (:meth:`accounts.models.EmployeeProfile.save`) i walidacji pola/formularza.
    """
    if not raw:
        return None
    cleaned = _PHONE_SEPARATORS_RE.sub("", str(raw).strip())
    if not cleaned:
        return None
    if not cleaned.startswith("+") and cleaned.isdigit():
        cleaned = "+" + cleaned
    return cleaned


def is_valid_e164(value: str | None) -> bool:
    """Czy ``value`` to ścisły numer E.164 zgodny z :data:`E164_RE`."""
    return bool(value and E164_RE.match(value))


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
