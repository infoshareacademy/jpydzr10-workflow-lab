"""Template tags + filters specific to the machines app.

Generic tags (status colours, date formatting, active link) live in
:mod:`core.templatetags.planer_tags` — reach for those first; only add
something here if it is genuinely machine-specific.
"""

from __future__ import annotations

from django import template
from django.templatetags.static import static
from django.utils.text import slugify

register = template.Library()


# Kolor kropki statusu przeglądu (Tailwind) per bucket — zamiast emoji.
# Kropka (``rounded-full``) jest wektorowa: ostra na każdym DPI, spójna
# cross-OS i z dark mode; emoji renderują się różnie na różnych systemach
# i łamią spójność ikon. Filtr zwraca SAMĄ klasę koloru (zwykły string,
# bez ``mark_safe``); HTML kropki składa szablon, a znaczenie niesie kolor
# + ``aria-label`` na tym samym ``<span>`` (spełnia „nie tylko kolor").
_INSPECTION_DOT_CLASSES: dict[str, str] = {
    "ok": "bg-emerald-500",
    "warning": "bg-amber-500",
    "overdue": "bg-rose-500",
    "unknown": "bg-slate-400 dark:bg-slate-500",
}


@register.filter
def inspection_dot(status: str) -> str:
    """Return the Tailwind background-colour class for an inspection bucket.

    The template renders the dot itself, keeping the colour decision here::

        {% load machines_tags %}
        <span class="inline-block h-3 w-3 rounded-full {{ machine.inspection_status|inspection_dot }}"
              aria-label="{{ machine.inspection_status_label }}"></span>
    """
    return _INSPECTION_DOT_CLASSES.get(status, _INSPECTION_DOT_CLASSES["unknown"])


# Manual Polish → ASCII transliteracja — sync z
# ``machines/management/commands/generate_machine_images._POLISH_ASCII_MAP``.
# Django ``slugify`` zna ó/ę/ą/ś/ć/ż/ź (NFKD strip), ale NIE zna ``ł``
# (LATIN SMALL LETTER L WITH STROKE — to nie diacritic, oddzielna litera).
# Bez tego ``wozek widłowy`` robi się ``wozek-widowy`` i obrazek 404'uje.
_POLISH_ASCII_MAP = str.maketrans({"ł": "l", "Ł": "L"})


@register.simple_tag
def machine_image_url(machine) -> str:
    """URL do obrazka maszyny — uploaded ImageField z fallbackiem na typ.

    Priorytet:

    1. ``machine.image`` (uploaded przez admina przez ImageField) — zwracamy
       ``machine.image.url`` (MEDIA_URL/machines/<file>),
    2. Fallback static: ``static/images/machines/<slug_typu>.webp`` — slug
       z ``Machine.Type.value`` przez ``slugify`` + Polish ASCII map (zob.
       ``_POLISH_ASCII_MAP``). Reference Imagen-generated katalog (Bundle 1).

    Zwracamy zawsze stringa (URL) — template renderuje bez branchowania
    na "is uploaded vs fallback". Jeśli kiedyś typ zniknie z katalogu
    static, ``static()`` zwróci niepustego stringa (404 dopiero przy
    fetchu z przeglądarki), więc template ma ``<img>`` zawsze z ``src``.

    Usage::

        {% load machines_tags %}
        <img src="{% machine_image_url machine %}"
             alt="Zdjęcie maszyny {{ machine.name }}"
             loading="lazy">
    """
    # 1. Uploaded image wygrywa — admin / user-supplied zdjęcie konkretnej
    #    instancji ma priorytet nad genericznym shot'em katalogu.
    uploaded = getattr(machine, "image", None)
    if uploaded:
        # ImageFieldFile is truthy iff a file is associated.
        try:
            return uploaded.url
        except ValueError:
            # `.url` rzuca jeśli field jest pusty (defensywnie, raczej nie
            # zdarzy się przy truthy uploaded). Fallthrough do static.
            pass

    # 2. Fallback po typie — zawsze powinien być .webp w static/images/machines/
    machine_type = getattr(machine, "machine_type", "") or ""
    slug = slugify(machine_type.translate(_POLISH_ASCII_MAP))
    if not slug:
        slug = "inne"
    return static(f"images/machines/{slug}.webp")
