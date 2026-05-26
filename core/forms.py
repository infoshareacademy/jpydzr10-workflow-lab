"""Wspólne stałe CSS Tailwind dla widgetów formularzy — DRY helper.

Wcześniej te stringi były duplikowane w 4 plikach ``<app>/forms.py``:
- ``accounts/forms.py`` (jako ``INPUT_CLASSES``, ze ``blue-500`` zamiast ``brand-500``)
- ``machines/forms.py`` (jako ``INPUT_CLASSES``)
- ``reservations/forms.py`` (jako ``INPUT_CSS`` / ``TEXTAREA_CSS`` / ``SELECT_CSS``)
- ``service/forms.py`` (jako ``INPUT_CSS`` / ``TEXTAREA_CSS`` / ``SELECT_CSS``)

Centralizacja gwarantuje że zmiana motywu (np. `brand-500` → `accent-500`)
jest jednoplikowa, oraz że accounts/forms.py używa tych samych focus-ringów
co reszta projektu (poprzednio rozjeżdżało się na `blue-500`).
"""

from __future__ import annotations

# Bazowa klasa dla `<input>` / `<select>` / `<textarea>`.
INPUT_CSS = (
    "block w-full rounded-md border-gray-300 dark:border-gray-600 "
    "dark:bg-gray-700 dark:text-gray-100 shadow-sm "
    "focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
)

# Wariant dla ``<textarea>`` — INPUT_CSS + minimalna wysokość.
TEXTAREA_CSS = INPUT_CSS + " min-h-[6rem]"

# Wariant dla ``<select>`` — identyczny z INPUT_CSS (alias dla czytelności
# w widgetach: ``forms.Select(attrs={"class": SELECT_CSS})`` mówi sens).
SELECT_CSS = INPUT_CSS

# Klasa dla ``<input type="file">`` — Tailwind stylizuje native button przez
# ``file:`` pseudo-elementy (selektory file:rounded itp.).
FILE_INPUT_CSS = (
    "block w-full text-sm text-gray-700 dark:text-gray-300 "
    "file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 "
    "file:text-sm file:font-medium file:bg-brand-100 file:text-brand-700 "
    "hover:file:bg-brand-200 dark:file:bg-brand-900/30 dark:file:text-brand-300"
)
