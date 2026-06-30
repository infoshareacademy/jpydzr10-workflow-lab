"""Strażnik: wieloliniowe komentarze ``{# ... #}`` renderują się dosłownie.

Django traktuje ``{# #}`` jako komentarz JEDNOLINIOWY — jeśli ``{#`` otwiera się
w jednej linii, a ``#}`` zamyka w kolejnej, lexer NIE rozpoznaje komentarza i
jego treść wycieka jako widoczny tekst na stronie (bug powtarzał się: dashboard
— commit 21c6b5e, karta maszyny — 2026-06-27). Ten test skanuje wszystkie
szablony projektu i wymusza komentarze jednoliniowe albo ``{% comment %}``.
"""

from __future__ import annotations

from pathlib import Path

# Korzeń projektu (…/jpydzr10-workflow-lab) — trzy poziomy nad tym plikiem.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Katalogi szablonów aplikacji + globalny ``templates/``. Pomijamy vendor/venv.
_TEMPLATE_GLOBS = ["templates", "*/templates"]
_EXCLUDE_PARTS = {".venv", "node_modules", "archive", "vendor"}


def _template_files() -> list[Path]:
    return [
        path
        for pattern in _TEMPLATE_GLOBS
        for path in _PROJECT_ROOT.glob(f"{pattern}/**/*.html")
        if not any(part in _EXCLUDE_PARTS for part in path.parts)
    ]


def _multiline_comment_lines(text: str) -> list[int]:
    """Numery linii, w których ``{#`` otwiera się bez ``#}`` w tej samej linii."""
    bad = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        idx = line.find("{#")
        if idx != -1 and "#}" not in line[idx + 2 :]:
            bad.append(lineno)
    return bad


def test_no_multiline_template_comments():
    offenders = []
    for path in _template_files():
        bad = _multiline_comment_lines(path.read_text(encoding="utf-8"))
        if bad:
            rel = path.relative_to(_PROJECT_ROOT)
            offenders.append(f"{rel}: linie {bad}")
    assert not offenders, (
        "Wieloliniowe komentarze {# #} wyciekają na stronę — scal do jednej linii "
        "albo użyj {% comment %}{% endcomment %}:\n" + "\n".join(offenders)
    )


def test_scanner_detects_known_pattern():
    """Sanity: skaner łapie wzorzec buga (i akceptuje komentarz jednoliniowy)."""
    assert _multiline_comment_lines("{# otwarte\n   zamkniete #}") == [1]
    assert _multiline_comment_lines("{# jedna linia #}") == []
