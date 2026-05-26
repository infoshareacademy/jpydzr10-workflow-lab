"""Testy helperów ``core.service_errors`` — mapowanie ValidationError → form.

``ValidationError`` ma trzy kształty:

* ``error_dict`` — błędy per pole (``ValidationError({"field": ["..."]})``),
* ``error_list`` — lista non-field errors (``ValidationError(["a", "b"])``),
* gołe ``ValidationError("msg")`` — pojedynczy komunikat.

Każdy z helperów (``add_form_errors`` i ``join_validation_error``) musi
obsłużyć wszystkie trzy kształty. Pokrywa lukę C3-9 / C3-10 z audytu —
do tej pory testy używały tylko jednego kształtu.
"""

from __future__ import annotations

import pytest
from django import forms
from django.core.exceptions import ValidationError

from core.service_errors import add_form_errors, join_validation_error


class _SampleForm(forms.Form):
    """Minimalny form z jednym polem — używamy go w testach jako target."""

    field = forms.CharField(required=True)


@pytest.mark.django_db
class TestAddFormErrors:
    """``add_form_errors`` — przepisuje exc → form.add_error per pole / __all__."""

    def test_add_validation_error_with_message_dict_known_field(self):
        """Klucz odpowiadający polu formularza → błąd ląduje przy tym polu."""
        form = _SampleForm(data={"field": "x"})
        form.is_valid()  # build form.errors infrastructure
        exc = ValidationError({"field": ["Custom error"]})
        add_form_errors(form, exc)
        assert "Custom error" in form.errors["field"]

    def test_add_validation_error_with_message_dict_unknown_field(self):
        """Klucz spoza pól formularza → ląduje w ``__all__`` (non-field)."""
        form = _SampleForm(data={"field": "x"})
        form.is_valid()
        exc = ValidationError({"unknown_field": ["Error from service"]})
        add_form_errors(form, exc)
        assert "Error from service" in form.errors["__all__"]

    def test_add_validation_error_with_message_list(self):
        """Lista (non-field errors) → wszystkie błędy do ``__all__``."""
        form = _SampleForm(data={"field": "x"})
        form.is_valid()
        exc = ValidationError(["Error A", "Error B"])
        add_form_errors(form, exc)
        all_errors = form.errors["__all__"]
        assert "Error A" in all_errors
        assert "Error B" in all_errors

    def test_add_single_message_validation_error(self):
        """Pojedynczy komunikat (``ValidationError("msg")``) → ``__all__``."""
        form = _SampleForm(data={"field": "x"})
        form.is_valid()
        exc = ValidationError("Pojedynczy błąd")
        add_form_errors(form, exc)
        assert "Pojedynczy błąd" in form.errors["__all__"]


class TestJoinValidationError:
    """``join_validation_error`` — flatten ValidationError → single string."""

    def test_join_with_message_dict_keeps_field_prefix(self):
        """Dict-shape: ``field: message`` separated by ``;``."""
        exc = ValidationError({"field_a": ["A1", "A2"], "field_b": ["B1"]})
        result = join_validation_error(exc)
        # Order może się różnić — sprawdzamy tylko obecność wszystkich części.
        assert "field_a: A1" in result
        assert "field_a: A2" in result
        assert "field_b: B1" in result
        # Separator ``; `` musi być użyty.
        assert "; " in result

    def test_join_with_message_dict_all_keyword_strips_prefix(self):
        """Klucz ``__all__`` w dict → message bez prefixu pola."""
        exc = ValidationError({"__all__": ["Global error"]})
        result = join_validation_error(exc)
        assert "Global error" in result
        # Nie chcemy zobaczyć ``__all__: Global error`` — strip prefix.
        assert "__all__" not in result

    def test_join_with_message_list(self):
        """Lista (non-field errors) → ``msg1; msg2``."""
        exc = ValidationError(["Error A", "Error B"])
        result = join_validation_error(exc)
        assert "Error A" in result
        assert "Error B" in result
        assert "; " in result

    def test_join_with_single_message(self):
        """Pojedynczy komunikat → string bez separatorów."""
        exc = ValidationError("Tylko jeden")
        result = join_validation_error(exc)
        assert "Tylko jeden" in result
