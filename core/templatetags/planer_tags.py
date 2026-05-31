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
# Wave 14 design system: amber/emerald/rose zamiast yellow/green/red (chłodniejsze
# tonacje, spójne z home / reservations / timeline). Slate dla terminalnych /
# wycofanych statusów (cooler gray, ten sam co reszta UI).
STATUS_COLOR_CLASSES = {
    # Statusy maszyn
    "W magazynie": "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
    "Na budowie": "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200",
    "Zarezerwowana": "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    "W serwisie": "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
    "Wycofana": (
        "bg-slate-200 text-slate-600 line-through "
        "dark:bg-slate-700/60 dark:text-slate-400"
    ),
    # Statusy rezerwacji
    "oczekująca": "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    "potwierdzona": "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
    "anulowana": "bg-slate-200 text-slate-600 dark:bg-slate-700/60 dark:text-slate-400",
    "zakończona": "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300",
}


@register.simple_tag
def status_badge(status_value):
    """Zwraca klasy CSS Tailwind dla badge'a statusu.

    Jeśli status nieznany — zwraca neutralne szare klasy z dark mode fallbackiem.
    """
    return STATUS_COLOR_CLASSES.get(
        status_value, "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300"
    )


@register.filter
def date_pl(value):
    """Filtr formatujący datę po polsku w formacie: 16.05.2026.

    Pusty string dla wartości None / falsy.
    """
    if not value:
        return ""
    return value.strftime("%d.%m.%Y")


@register.simple_tag(takes_context=True)
def active_link(context, url_path, css_class="bg-slate-100 dark:bg-slate-700"):
    """Zwraca klasę CSS jeśli current_path zaczyna się od `url_path`.

    Helper do oznaczania aktywnego linku w nawigacji. Wymaga context processora
    `core.context_processors.navigation`, który dostarcza `current_path`.
    """
    current = context.get("current_path", "")
    return css_class if current.startswith(url_path) else ""


# Statusy budow maja inne semantyczne kolory niz rezerwacje:
# - aktywna  = zielony  (vs rezerwacja "potwierdzona" tez zielona — spojne)
# - zakonczona = szary  (terminalny stan)
# - anulowana = czerwony (vs rezerwacja "anulowana" szara — budowa anulowana
#   to bardziej znaczace zdarzenie biznesowe, podkreslamy kolorem)
# Dlatego osobny mapping zamiast nadpisywania kluczy w STATUS_COLOR_CLASSES
# (rezerwacja "anulowana" zostala by przemalowana na czerwono niechcacy).
SITE_STATUS_COLOR_CLASSES = {
    "aktywna": "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
    "zakończona": "bg-slate-200 text-slate-600 dark:bg-slate-700/60 dark:text-slate-400",
    "anulowana": "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
}


@register.simple_tag
def site_status_badge(status_value):
    """Klasy CSS dla badge'a statusu budowy (rozne od rezerwacji)."""
    return SITE_STATUS_COLOR_CLASSES.get(
        status_value, "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300"
    )


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
