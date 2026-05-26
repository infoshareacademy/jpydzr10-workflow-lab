"""Tests dla ``machines.templatetags.machines_tags``.

Sprawdzamy:

* ``inspection_icon`` — mapping bucket → emoji, fallback dla unknown,
* ``machine_image_url`` — uploaded ImageField wygrywa, fallback po
  ``machine_type`` z Polish ASCII transliteracją (``ł``→``l``, etc.).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.template import Context, Template

from machines.models import Machine
from machines.templatetags.machines_tags import inspection_icon, machine_image_url

# =============================================================================
# inspection_icon
# =============================================================================


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", "✅"),
        ("warning", "⚠️"),
        ("overdue", "🔴"),
        ("unknown", "❓"),
        ("nieznany_bucket", "❓"),  # fallback dla nieznanego stringa
        ("", "❓"),  # pusty string → fallback
    ],
)
def test_inspection_icon_mapping(status: str, expected: str) -> None:
    """Każdy bucket statusu przeglądu mapuje się na właściwą emoji."""
    assert inspection_icon(status) == expected


# =============================================================================
# machine_image_url — fallback po typie
# =============================================================================


@pytest.mark.parametrize(
    ("machine_type", "expected_slug"),
    [
        # Bez polskich znaków — Django slugify wystarcza.
        ("koparka", "koparka"),
        ("minikoparka", "minikoparka"),
        ("walec", "walec"),
        ("spawarka", "spawarka"),
        ("inne", "inne"),
        # ó/ę/ą/ś/ć/ż/ź → NFKD strip (Django slugify ogarnia).
        ("podnośnik nożycowy", "podnosnik-nozycowy"),
        ("podnośnik teleskopowy", "podnosnik-teleskopowy"),
        ("agregat prądotwórczy", "agregat-pradotworczy"),
        ("zagęszczarka", "zageszczarka"),
        # ``ł`` wymaga manual ASCII map — bez tego ``widłowy`` → ``widowy``.
        ("wózek widłowy", "wozek-widlowy"),
    ],
)
def test_machine_image_url_fallback_per_type(machine_type: str, expected_slug: str) -> None:
    """Bez ``image`` zwracamy ``/static/images/machines/<slug>.webp``."""
    machine = Machine(uid="TEST-001", name="Test", machine_type=machine_type)
    url = machine_image_url(machine)
    assert url == f"/static/images/machines/{expected_slug}.webp"


def test_machine_image_url_uploaded_wins() -> None:
    """Gdy ``machine.image`` jest ustawione, wraca ``.url`` (nie fallback)."""
    machine = Machine(uid="TEST-002", name="Test", machine_type="koparka")
    # Symulujemy uploaded ImageFieldFile — `.url` musi zwrócić MEDIA_URL path.
    with patch.object(
        type(machine).image,
        "__get__",
        return_value=type(
            "FakeFieldFile", (), {"__bool__": lambda s: True, "url": "/media/machines/custom.jpg"}
        )(),
    ):
        # Bezpieczniej: bezpośrednio przypisać.
        pass
    # Direct attribute injection (Image not really uploaded — testujemy logic).

    class _FakeFile:
        def __bool__(self) -> bool:  # truthy
            return True

        url = "/media/machines/custom.jpg"

    machine.image = _FakeFile()  # type: ignore[assignment]
    assert machine_image_url(machine) == "/media/machines/custom.jpg"


def test_machine_image_url_empty_type_falls_back_to_inne() -> None:
    """Defensive: brak typu → ``inne.webp`` (a nie pusty slug → 404)."""
    machine = Machine(uid="TEST-003", name="Test", machine_type="")
    url = machine_image_url(machine)
    assert url == "/static/images/machines/inne.webp"


def test_machine_image_url_uploaded_url_raises_falls_through() -> None:
    """Jeśli ``.url`` rzuca ``ValueError`` (empty FieldFile), wraca static."""

    class _BrokenFile:
        def __bool__(self) -> bool:
            return True

        @property
        def url(self) -> str:
            raise ValueError("The 'image' attribute has no file associated.")

    machine = Machine(uid="TEST-004", name="Test", machine_type="walec")
    machine.image = _BrokenFile()  # type: ignore[assignment]
    assert machine_image_url(machine) == "/static/images/machines/walec.webp"


# =============================================================================
# Render w template — integration check
# =============================================================================


def test_machine_image_url_renders_in_template() -> None:
    """Tag jest dostępny po ``{% load machines_tags %}`` i renderuje URL."""
    machine = Machine(uid="TEST-005", name="Test", machine_type="koparka")
    tpl = Template("{% load machines_tags %}{% machine_image_url m as u %}{{ u }}")
    rendered = tpl.render(Context({"m": machine}))
    assert rendered == "/static/images/machines/koparka.webp"
