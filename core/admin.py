"""Wspólne klasy bazowe dla django-admin (unfold theme + simple_history).

Ustandaryzowanie MRO: ``ModelAdmin`` (unfold) MUSI być pierwszy zgodnie z
oficjalną dokumentacją django-unfold — w przeciwnym razie unfoldowy theme
nie nakłada się na widoki nadpisywane przez ``SimpleHistoryAdmin`` (history
list, history detail). Dzięki temu jeden ``PlanerHistoryAdmin`` zastępuje
verbatim duplikaty ``class _UnfoldHistoryAdmin(...)`` w każdej aplikacji.
"""

from __future__ import annotations

from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin


class PlanerHistoryAdmin(ModelAdmin, SimpleHistoryAdmin):
    """Bazowa klasa dla wszystkich ``ModelAdmin`` używających simple_history.

    Łączy:

    * ``unfold.admin.ModelAdmin`` — Tailwind styling, dashboard widgets,
      consistent input/button look.
    * ``simple_history.admin.SimpleHistoryAdmin`` — przycisk *Historia* +
      detail-view per rewizja na liście admina.
    """
