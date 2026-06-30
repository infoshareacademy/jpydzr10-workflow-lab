"""Normalizuje istniejące numery telefonów do formatu E.164 przed nałożeniem
ograniczenia ``unique`` (krok 2 z 3 trójstopniowej migracji telefonu).

* puste stringi (``""``) → ``NULL`` (sentinel braku numeru musi być NULL, nie
  ``""`` — dwa puste stringi złamałyby przyszłą unikalność),
* numery z separatorami (spacje, myślniki, nawiasy) → oczyszczone do E.164,
* numery niedające się sparsować → ``NULL``,
* duplikaty → pierwszy zostaje, kolejne ``NULL`` (unikalność wymaga pojedynczego
  właściciela danego numeru).
"""

from __future__ import annotations

import re

from django.db import migrations

# Akceptowalny kształt E.164 po oczyszczeniu: "+" + cyfra 1-9 + 7-14 cyfr.
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
# Znaki separujące usuwane przed próbą parsowania (spacje, myślniki, nawiasy, kropki).
_SEP_RE = re.compile(r"[\s\-().]")


def _to_e164(raw: str | None) -> str | None:
    """Best-effort normalizacja pojedynczego numeru do E.164 lub ``None``."""
    if not raw:
        return None
    cleaned = _SEP_RE.sub("", raw.strip())
    if not cleaned:
        return None
    # Numer bez "+" ale z samymi cyframi traktujemy jako już-międzynarodowy
    # tylko jeśli zaczyna się od cyfry 1-9 i ma sensowną długość; w przeciwnym
    # razie nie zgadujemy kierunkowego — bezpieczniej zostawić NULL.
    if not cleaned.startswith("+") and cleaned.isdigit():
        cleaned = "+" + cleaned
    return cleaned if _E164_RE.match(cleaned) else None


def normalize_phones(apps, schema_editor):
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")

    seen: set[str] = set()
    for profile in EmployeeProfile.objects.all().order_by("pk").iterator(chunk_size=500):
        e164 = _to_e164(profile.phone)
        if e164 is not None and e164 in seen:
            e164 = None  # duplikat — pierwszy zachowuje numer, reszta NULL
        if e164 is not None:
            seen.add(e164)
        if profile.phone != e164:
            profile.phone = e164
            profile.save(update_fields=["phone"])


def noop_reverse(apps, schema_editor):
    """Reverse jest no-op — oryginalnych (nieznormalizowanych) numerów nie
    odtwarzamy, ale migracja musi być odwracalna dla testów round-trip."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_alter_employeeprofile_phone_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_phones, noop_reverse),
    ]
