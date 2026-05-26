"""Generate per-type machine catalogue images via Imagen 4 (Google AI).

Wytwarzamy JEDEN obrazek per ``Machine.Type`` (10 typów) zamiast per-instancję,
bo:

* katalog 10 000-osobowej firmy potrzebuje **spójnego visualu** — wszystkie
  koparki KOP-001…KOP-005 powinny mieć ten sam reference shot, tak samo
  jak w katalogach CAT czy Volvo,
* per-instancję = 20 generacji = ~5x koszt,
* tła i kąt ujęcia są ujednolicone (white seamless, 3/4 angle) — w UI
  thumbnaile siadają w spójną siatkę bez chaotycznych perspektyw.

Cost guardrail: Imagen 4 ~$0.04/obraz x 10 typów = ~$0.40 jednorazowo.
Mocno poniżej limitu $10/mc z ``.env``.

Pipeline:

1. ``GenerateImagesConfig(aspect_ratio="1:1", number_of_images=1)``
2. Pillow resize do 512x512 LANCZOS
3. WebP (quality=85) — typowy thumbnail 30-60 KB, ~6x mniej niż JPEG q90
4. Zapis do ``static/images/machines/<slug>.webp``

Slug generujemy z polskich ``Type.value`` (np. ``"podnośnik nożycowy"``)
przez ``unidecode`` + ``slugify`` żeby filename był ASCII-safe i kompatybilny
z ``{% static %}`` URL (no diacritics, no spaces).

Usage::

    DJANGO_SETTINGS_MODULE=planer_config.settings.dev \\
        uv run python manage.py generate_machine_images

    # albo tylko jeden typ:
    uv run python manage.py generate_machine_images --type koparka

    # --force (regen istniejących):
    uv run python manage.py generate_machine_images --force
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify
from PIL import Image

from machines.models import Machine

# Per-type prompt — opis maszyny po angielsku (Imagen pre-trained na enwiki),
# z ujednoliconym suffixem produktowym. Klucz to ``Machine.Type.value``
# (polski tekst), więc enum-loop nigdy nie zgubi się z nowym typem.
PROMPT_DESCRIPTIONS: dict[str, str] = {
    Machine.Type.KOPARKA.value: (
        "professional product photograph of a yellow construction excavator, "
        "modern hydraulic crawler excavator with bucket arm extended, "
        "Caterpillar / Volvo style heavy equipment"
    ),
    Machine.Type.MINIKOPARKA.value: (
        "professional product photograph of a compact mini excavator, "
        "1.5 to 3 tonne class, yellow rubber-track machine with small bucket, "
        "modern construction equipment"
    ),
    Machine.Type.PODNOSNIK_NOZYCOWY.value: (
        "professional product photograph of an industrial scissor lift "
        "platform, electric aerial work platform with extended scissor "
        "mechanism, yellow safety rails, modern construction equipment"
    ),
    Machine.Type.PODNOSNIK_TELESKOPOWY.value: (
        "professional product photograph of a telescopic boom lift, "
        "articulating aerial work platform with extended boom, "
        "yellow basket, modern construction equipment"
    ),
    Machine.Type.AGREGAT.value: (
        "professional product photograph of a portable diesel power "
        "generator unit, enclosed industrial silent generator on wheels, "
        "yellow steel housing, modern construction equipment"
    ),
    Machine.Type.WOZEK_WIDLOWY.value: (
        "professional product photograph of an industrial forklift truck, "
        "yellow counterbalance warehouse forklift with steel forks, "
        "modern Toyota / Linde style materials handling equipment"
    ),
    Machine.Type.WALEC.value: (
        "professional product photograph of a tandem road roller, "
        "smooth-drum vibratory compactor with two large steel drums, "
        "yellow construction equipment for asphalt and soil compaction"
    ),
    Machine.Type.ZAGESZCZARKA.value: (
        "professional product photograph of a plate compactor, "
        "walk-behind vibrating soil compactor with steel base plate "
        "and handle, yellow construction equipment"
    ),
    Machine.Type.SPAWARKA.value: (
        "professional product photograph of an industrial MIG welder, "
        "portable inverter welding machine on wheels with cable reel, "
        "yellow industrial equipment"
    ),
    Machine.Type.INNE.value: (
        "professional product photograph of a generic construction tool kit "
        "on a small wheeled trolley, yellow heavy-duty industrial equipment, "
        "modern construction site accessories"
    ),
}

# Wspólny suffix — uniform white seamless background, soft studio lighting,
# 3/4 angle, no people / text. Trzymamy go w jednej stałej żeby nie powtarzać
# 10x w ``PROMPT_DESCRIPTIONS`` i żeby zmiana stylistyki była jednoliniowa.
PROMPT_SUFFIX = (
    ", photographed in a clean industrial product studio, "
    "white seamless cyclorama background, soft top-down studio lighting, "
    "3/4 angle front-right view, sharp focus, high detail, "
    "no people, no text overlays, no logos, no watermarks, "
    "photorealistic 8K commercial product photography, "
    "shot for a serious construction equipment company catalogue"
)


# Imagen 4 model ID. Sebastian może override przez ENV jeśli kiedyś
# zechce ultra/fast wariant.
IMAGEN_MODEL = os.environ.get("IMAGEN_MODEL", "imagen-4.0-generate-001")

# Output thumbnail size — 512 wystarcza dla grid 16:10 (typowo 320-400 wide
# rendered) i detail header (max 400x400). Większe = WebP file bloat.
THUMBNAIL_SIZE = (512, 512)
WEBP_QUALITY = 85

OUTPUT_DIR = Path(settings.BASE_DIR) / "static" / "images" / "machines"


# Manual Polish → ASCII transliteracja. Django ``slugify`` zna ó/ę/ą/ś/ć/ż/ź
# (Unicode NFKD strip), ale NIE zna ``ł`` (LATIN SMALL LETTER L WITH STROKE,
# bo to nie jest diacritic — to oddzielna litera). Bez tego ``widłowy``
# robi się ``widowy`` (przy tłumaczeniu na ``widlowy``). Map jest minimalny —
# tylko ``ł``/``Ł``, reszta robi Django.
_POLISH_ASCII_MAP = str.maketrans({"ł": "l", "Ł": "L"})


def _slug_for_type(type_value: str) -> str:
    """Konwertuje polski ``Machine.Type.value`` na ASCII filename slug.

    Przykład: ``"podnośnik nożycowy"`` → ``"podnosnik-nozycowy"``,
    ``"wózek widłowy"`` → ``"wozek-widlowy"`` (wymaga ``_POLISH_ASCII_MAP``
    bo Django slugify nie tłumaczy ``ł`` → ``l``).
    """
    return slugify(type_value.translate(_POLISH_ASCII_MAP))


def _build_prompt(type_value: str) -> str:
    """Składa opis maszyny + uniform suffix w jeden Imagen prompt."""
    base = PROMPT_DESCRIPTIONS.get(type_value)
    if not base:
        # Failsafe — jeśli ktoś doda nowy Machine.Type i zapomni o prompt,
        # użyjemy genericznego "construction equipment".
        base = f"professional product photograph of a {type_value}, construction equipment"
    return base + PROMPT_SUFFIX


class Command(BaseCommand):
    """Management command — generuje obrazki maszyn per type przez Imagen."""

    help = (
        "Generuje katalogowe obrazki maszyn (jeden per Machine.Type) przez "
        "Imagen 4 (Google AI) i zapisuje jako WebP 512x512 w "
        "static/images/machines/<slug>.webp."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--type",
            type=str,
            default=None,
            help=(
                "Wygeneruj tylko jeden typ (Machine.Type.value, "
                "np. 'koparka'). Bez tej flagi generujemy wszystkie 10 typów."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regeneruj nawet jeśli plik .webp już istnieje.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pokaż plan, nie wywołuj API i nie zapisuj plików.",
        )

    def handle(self, *args, **options) -> None:
        # Lazy import — google-genai jest ciężki (boto3 etc.), nie chcemy
        # ładować go przy każdym ``manage.py``. CommandError zamiast crash
        # jeśli biblioteka nieobecna w sandboxie.
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover (zależność opcjonalna)
            raise CommandError(
                "Pakiet 'google-genai' nie jest zainstalowany. Uruchom: uv add google-genai"
            ) from exc

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise CommandError(
                "Brak GEMINI_API_KEY w środowisku. Dodaj do .env i odpal:\n"
                "  export $(grep -v '^#' .env | xargs)"
            )

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Filter listy typów (--type override)
        target_types = list(PROMPT_DESCRIPTIONS.keys())
        if options["type"]:
            if options["type"] not in PROMPT_DESCRIPTIONS:
                raise CommandError(
                    f"Nieznany typ: {options['type']!r}. "
                    f"Dostępne: {', '.join(PROMPT_DESCRIPTIONS.keys())}"
                )
            target_types = [options["type"]]

        client = None if options["dry_run"] else genai.Client(api_key=api_key)

        ok = 0
        skipped = 0
        failed = 0

        for type_value in target_types:
            slug = _slug_for_type(type_value)
            out_path = OUTPUT_DIR / f"{slug}.webp"

            if out_path.exists() and not options["force"]:
                self.stdout.write(
                    self.style.WARNING(f"= {slug}.webp już istnieje — pomijam (użyj --force)")
                )
                skipped += 1
                continue

            prompt = _build_prompt(type_value)

            if options["dry_run"]:
                self.stdout.write(f"[DRY-RUN] {slug}.webp ← {prompt[:80]}...")
                continue

            try:
                self.stdout.write(f"… generuję {slug}.webp przez {IMAGEN_MODEL}…")
                response = client.models.generate_images(
                    model=IMAGEN_MODEL,
                    prompt=prompt,
                    config=genai_types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="1:1",
                        output_mime_type="image/jpeg",
                        # safety: konstrukcyjny sprzęt jest OK dla wszystkich
                        # filtrów, ale ustawmy permissive na PERSON żeby Imagen
                        # nie zgłaszał false-positive jeśli case'm wygeneruje
                        # operatora kabinie.
                        person_generation="dont_allow",
                    ),
                )

                if not response.generated_images:
                    self.stderr.write(self.style.ERROR(f"✗ {slug}: pusta odpowiedź"))
                    failed += 1
                    continue

                img_bytes = response.generated_images[0].image.image_bytes

                # PIL resize → WebP. ``thumbnail`` zachowuje aspect ratio i nie
                # upscale'uje (Imagen daje 1024x1024+ natywnie).
                img = Image.open(io.BytesIO(img_bytes))
                img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
                # WebP nie obsługuje YCbCr (z JPEG) zawsze — konwersja do RGB.
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(out_path, "webp", quality=WEBP_QUALITY, method=6)

                size_kb = out_path.stat().st_size / 1024
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ {slug}.webp ({img.size[0]}x{img.size[1]}, {size_kb:.1f} KB)"
                    )
                )
                ok += 1
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"✗ {slug}: {exc!s}"))
                failed += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Gotowe — wygenerowane: {ok}, pominięte: {skipped}, błędy: {failed}"
            )
        )
        if not options["dry_run"]:
            self.stdout.write(f"  Katalog: {OUTPUT_DIR}")
