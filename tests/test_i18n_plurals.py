"""Plural / translation correctness checks for the PL/EN catalogs.

These tests lock in the behaviour of the gettext machinery without needing a
running server: they exercise :mod:`django.utils.translation` directly under
``translation.override`` so they are fully deterministic.

Two things are verified:

1. A handful of stable UI strings translate to English under ``override("en")``
   and fall back to the Polish source under ``override("pl")``.
2. Pluralised messages (``blocktrans count`` / ``ngettext``) pick the correct
   form for ``n == 1`` vs ``n == 5`` in both languages. English uses the
   two-form ``n != 1`` rule; Polish uses its three-form rule, so the catalog
   itself only carries the EN two-form variants — what we assert here is that
   the *English* output flips singular -> plural while the *Polish* source
   strings stay distinct.
"""

from __future__ import annotations

from django.utils.translation import gettext, ngettext, override

# A representative sample of msgids that are translated in
# ``locale/en/LC_MESSAGES/django.po``. Each maps PL source -> expected EN.
_SAMPLE_TRANSLATIONS = {
    "Oczekująca": "Pending",
    "Potwierdzona": "Confirmed",
    "Anulowana": "Cancelled",
    "Zakończona": "Completed",
    "Maszyna": "Machine",
    "Rezerwacja": "Reservation",
    "Lista rezerwacji": "Reservation list",
    "Numer projektu": "Project number",
}


def test_known_string_translates_to_english():
    """A stable label translates to its English msgstr under override('en')."""
    with override("en"):
        assert gettext("Lista rezerwacji") == "Reservation list"
        assert gettext("Oczekująca") == "Pending"


def test_known_string_returns_polish_source_under_pl():
    """Under override('pl') gettext returns the Polish source verbatim."""
    with override("pl"):
        # 'pl' is LANGUAGE_CODE / the source language, so the msgid is echoed.
        assert gettext("Lista rezerwacji") == "Lista rezerwacji"
        assert gettext("Oczekująca") == "Oczekująca"


def test_representative_sample_all_translated_in_english():
    """Every sampled msgid resolves to a non-empty, distinct English string."""
    with override("en"):
        for source, expected_en in _SAMPLE_TRANSLATIONS.items():
            translated = gettext(source)
            assert translated == expected_en, (
                f"{source!r} -> {translated!r}, expected {expected_en!r}"
            )
            assert translated.strip(), f"empty EN translation for {source!r}"


def test_blocktrans_count_plural_english_singular_vs_plural():
    """The 'budowa/budów' counter flips singular -> plural for n=1 vs n=5 (EN)."""
    singular = "(%(counter)s budowa)"
    plural = "(%(counter)s budów)"
    with override("en"):
        one = ngettext(singular, plural, 1) % {"counter": 1}
        many = ngettext(singular, plural, 5) % {"counter": 5}
    assert one == "(1 site)"
    assert many == "(5 sites)"
    assert one != many


def test_maps_counter_plural_english_singular_vs_plural():
    """The maps 'machine(s) on the map' counter agrees for n=1 vs n=5 (EN)."""
    singular = "%(counter)s maszyna na mapie. Klik pin -> szczegoly."
    plural = "%(counter)s maszyn na mapie. Klik pin -> szczegoly."
    with override("en"):
        one = ngettext(singular, plural, 1) % {"counter": 1}
        many = ngettext(singular, plural, 5) % {"counter": 5}
    assert one == "1 machine on the map. Click a pin -> details."
    assert many == "5 machines on the map. Click a pin -> details."
    assert one != many


def test_polish_plural_source_forms_are_distinct():
    """Under override('pl') the singular and plural sources stay distinct.

    Polish uses a 3-form plural rule; both n=1 and n=5 fall into *different*
    forms than each other, so ngettext must not collapse them to one string.
    """
    singular = "(%(counter)s budowa)"
    plural = "(%(counter)s budów)"
    with override("pl"):
        one = ngettext(singular, plural, 1) % {"counter": 1}
        many = ngettext(singular, plural, 5) % {"counter": 5}
    assert one == "(1 budowa)"
    assert many == "(5 budów)"
    assert one != many
