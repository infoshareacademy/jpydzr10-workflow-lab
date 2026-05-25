"""Template tags i filtry współdzielone przez wszystkie aplikacje.

Użycie w template:
    {% load planer_tags %}
    <span class="{% status_badge machine.status %}">{{ machine.status }}</span>
    <p>Data: {{ reservation.start_date|date_pl }}</p>
    <a class="px-3 py-2 {% active_link '/machines/' %}">Maszyny</a>
"""

from datetime import date as _date_cls

from django import template

register = template.Library()


# Klasy CSS Tailwind dla statusów (per ZASADA #2 — polskie statusy z M1).
STATUS_COLOR_CLASSES = {
    # Statusy maszyn
    "W magazynie": "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
    "Na budowie": "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200",
    "Zarezerwowana": "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200",
    "W serwisie": "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
    # Statusy rezerwacji
    "oczekująca": "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200",
    "potwierdzona": "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
    "anulowana": "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
    "zakończona": "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
}


@register.simple_tag
def status_badge(status_value):
    """Zwraca klasy CSS Tailwind dla badge'a statusu.

    Jeśli status nieznany — zwraca neutralne szare klasy.
    """
    return STATUS_COLOR_CLASSES.get(status_value, "bg-gray-100 text-gray-700")


@register.filter
def date_pl(value):
    """Filtr formatujący datę po polsku w formacie: 16.05.2026.

    Pusty string dla wartości None / falsy.
    """
    if not value:
        return ""
    return value.strftime("%d.%m.%Y")


@register.simple_tag(takes_context=True)
def active_link(context, url_path, css_class="bg-gray-100 dark:bg-gray-700"):
    """Zwraca klasę CSS jeśli current_path zaczyna się od `url_path`.

    Helper do oznaczania aktywnego linku w nawigacji. Wymaga context processora
    `core.context_processors.navigation`, który dostarcza `current_path`.
    """
    current = context.get("current_path", "")
    return css_class if current.startswith(url_path) else ""


# Mapowanie statusu rezerwacji na klase CSS bara timeline (slugified bez
# diakrytyk bo CSS classy nie lubia non-ASCII w pewnych przegladarkach + linterach).
BAR_CLASS_MAP = {
    "oczekująca": "status-oczekujaca",
    "potwierdzona": "status-potwierdzona",
    "anulowana": "status-anulowana",
    "zakończona": "status-zakonczona",
}


@register.simple_tag
def bar_class_for(status_value):
    """Zwraca klasę CSS Tailwind/custom dla bara timeline.

    Mapuje polskie statusy rezerwacji (z diakrytykami) na ascii-safe css
    klasy zdefiniowane w `static/css/custom.css` (.status-oczekujaca itp.).
    """
    return BAR_CLASS_MAP.get(status_value, "status-potwierdzona")


# Krotkie nazwy dni tygodnia po polsku (Pn..Nd).
DAY_NAMES_PL = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]


@register.filter
def day_short(value):
    """Skrocony dzien tygodnia po polsku dla `datetime.date`."""
    if not value:
        return ""
    try:
        return DAY_NAMES_PL[value.weekday()]
    except AttributeError:
        return ""
    except IndexError:  # pragma: no cover — date.weekday() zawsze 0..6, defensive only
        return ""


@register.filter
def is_weekend(value):
    """True dla soboty/niedzieli (date.weekday() in (5, 6))."""
    try:
        return value.weekday() >= 5
    except AttributeError:
        return False


@register.filter
def is_today(value):
    """True kiedy `value` to dzisiejsza data."""
    try:
        return value == _date_cls.today()
    except AttributeError:  # pragma: no cover — `==` z date zwraca False bez exc
        return False
    except ValueError:  # pragma: no cover — defensive (date eq nie rzuca ValueError)
        return False
