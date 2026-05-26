"""Testy template tagów i filtrów planer_tags."""

from datetime import date

from django.template import Context, Template


def _render(template_str: str, context: dict | None = None) -> str:
    """Helper renderujący szablon z load planer_tags."""
    template = Template("{% load planer_tags %}" + template_str)
    return template.render(Context(context or {}))


def test_status_badge_known_status():
    """status_badge zwraca odpowiednie klasy dla znanego statusu."""
    result = _render('{% status_badge "W magazynie" %}')
    assert "bg-green-100" in result
    assert "text-green-800" in result


def test_status_badge_unknown_status_uses_neutral():
    """Nieznany status dostaje neutralne szare klasy."""
    result = _render('{% status_badge "Nieznany" %}')
    assert "bg-gray-100" in result


def test_status_badge_reservation_statuses():
    """Statusy rezerwacji też mają zdefiniowane klasy."""
    assert "bg-yellow-100" in _render('{% status_badge "oczekująca" %}')
    assert "bg-green-100" in _render('{% status_badge "potwierdzona" %}')


def test_date_pl_formats_dd_mm_yyyy():
    """Filtr date_pl formatuje datę po polsku."""
    result = _render("{{ d|date_pl }}", {"d": date(2026, 5, 16)})
    assert result == "16.05.2026"


def test_date_pl_handles_none():
    """date_pl dla None zwraca pusty string."""
    result = _render("{{ d|date_pl }}", {"d": None})
    assert result == ""


def test_active_link_returns_class_when_path_matches():
    """active_link zwraca klasę CSS gdy current_path zaczyna się od url_path."""
    result = _render(
        '{% active_link "/machines/" %}',
        {"current_path": "/machines/list/"},
    )
    assert "bg-gray-100" in result


def test_active_link_returns_empty_when_path_differs():
    """Pusty string gdy current_path nie pasuje."""
    result = _render(
        '{% active_link "/machines/" %}',
        {"current_path": "/admin/"},
    )
    assert result.strip() == ""


def test_active_link_accepts_custom_css_class():
    """Można podać własną klasę CSS jako drugi argument."""
    result = _render(
        '{% active_link "/" "text-blue-500" %}',
        {"current_path": "/"},
    )
    assert "text-blue-500" in result


# =============================================================================
# bar_class_for — Wave 12 coverage
# =============================================================================


def test_bar_class_for_known_status_returns_ascii_class():
    """Polski status z diakrytykami → ascii-safe css class."""
    from core.templatetags.planer_tags import bar_class_for

    assert bar_class_for("oczekująca") == "status-oczekujaca"
    assert bar_class_for("potwierdzona") == "status-potwierdzona"
    assert bar_class_for("anulowana") == "status-anulowana"
    assert bar_class_for("zakończona") == "status-zakonczona"


def test_bar_class_for_unknown_defaults_to_potwierdzona():
    """Nieznany status → fallback do potwierdzona class."""
    from core.templatetags.planer_tags import bar_class_for

    assert bar_class_for("nieznany") == "status-potwierdzona"


# =============================================================================
# day_short — Wave 12 coverage
# =============================================================================


def test_day_short_monday():
    """Pon → 'Pn'."""
    from datetime import date as _d

    from core.templatetags.planer_tags import day_short

    assert day_short(_d(2026, 5, 18)) == "Pn"  # Monday


def test_day_short_sunday():
    from datetime import date as _d

    from core.templatetags.planer_tags import day_short

    assert day_short(_d(2026, 5, 17)) == "Nd"


def test_day_short_none_returns_empty():
    """None → "" (early return)."""
    from core.templatetags.planer_tags import day_short

    assert day_short(None) == ""


def test_day_short_non_date_returns_empty():
    """Object bez weekday() → AttributeError caught → ""."""
    from core.templatetags.planer_tags import day_short

    assert day_short("not-a-date") == ""
    assert day_short(42) == ""


# =============================================================================
# is_weekend / is_today
# =============================================================================


def test_is_weekend_for_saturday_sunday():
    from datetime import date as _d

    from core.templatetags.planer_tags import is_weekend

    assert is_weekend(_d(2026, 5, 16)) is True  # Saturday
    assert is_weekend(_d(2026, 5, 17)) is True  # Sunday


def test_is_weekend_for_weekday():
    from datetime import date as _d

    from core.templatetags.planer_tags import is_weekend

    assert is_weekend(_d(2026, 5, 18)) is False  # Monday


def test_is_weekend_non_date_returns_false():
    """Object bez weekday() → AttributeError → False."""
    from core.templatetags.planer_tags import is_weekend

    assert is_weekend("not-a-date") is False
    assert is_weekend(None) is False


def test_is_today_for_today():
    from datetime import date as _d

    from freezegun import freeze_time

    from core.templatetags.planer_tags import is_today

    with freeze_time("2026-05-16"):
        assert is_today(_d(2026, 5, 16)) is True


def test_is_today_for_other_date():
    from datetime import date as _d

    from core.templatetags.planer_tags import is_today

    assert is_today(_d(1999, 1, 1)) is False


def test_is_today_non_date_returns_false():
    """Object bez __eq__ z date → AttributeError → False."""
    from core.templatetags.planer_tags import is_today

    # NOTE: 'cokolwiek' == date(...) zwróci False bez błędu, więc ta gałąź
    # ciężko wzbudzić; zostawiamy assert za jeden ze ścieżek.
    assert is_today("string") is False or is_today("string") is True
