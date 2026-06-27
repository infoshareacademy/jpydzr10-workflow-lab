"""Globalna konfiguracja pytest (fixtures wspólne dla całego projektu)."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.utils import translation


@pytest.fixture(autouse=True)
def _reset_active_language():
    """Resetuj aktywny język interfejsu po KAŻDYM teście.

    Żądania przez test client z nagłówkiem ``HTTP_ACCEPT_LANGUAGE`` albo
    ciasteczkiem języka aktywują dany język w wątku (``LocaleMiddleware``),
    a pytest-django nie przywraca go między testami. Pod współbieżnym ``xdist``
    aktywne „en" wyciekało do kolejnego testu na tym samym workerze — przez co
    komunikaty ``ValidationError`` renderowały się po angielsku i asercje na
    polski tekst (``match="..."``) padały niedeterministycznie (flaky CI).

    Twardo aktywujemy język domyślny (``settings.LANGUAGE_CODE`` = pl) po każdym
    teście, dzięki czemu stan języka nigdy nie przecieka.
    """
    yield
    translation.activate(settings.LANGUAGE_CODE)
