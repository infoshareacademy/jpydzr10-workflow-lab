# Planer Maszyn Budowlanych

System rezerwacji i serwisu maszyn budowlanych dla małej firmy budowlanej.

> **Status projektu:** Milestone 2 — aplikacja webowa Django (w trakcie budowy).
> Milestone 1 (aplikacja konsolowa) został zakończony i przeniesiony do
> [`archive/milestone-1/`](archive/milestone-1/) jako materiał referencyjny.

## Cel Milestone 2

Przeniesienie funkcjonalności aplikacji konsolowej (175 testów PASS) na
interfejs webowy w Django 5.2 LTS, z dojrzałym stackiem produkcyjnym
(PostgreSQL, HTMX, Alpine.js, Tailwind, django-unfold) oraz panelu
administracyjnego — wszystko po polsku, gotowe na prezentację 14.06.2026.

Pełny plan i podział na sprinty: [`JIRA_TASKS_Milestone2.md`](JIRA_TASKS_Milestone2.md).

## Funkcjonalność (cel końcowy M2)

- Inwentarz maszyn z oznaczeniami terminów przeglądów technicznych.
- Rezerwacje maszyn z wykrywaniem konfliktów terminów.
- Codzienna synchronizacja statusów (Hard Return Policy).
- Rejestr serwisowy (przeglądy + naprawy) z automatycznym obliczaniem
  terminu kolejnego przeglądu.
- Budowy (`ConstructionSite`) z numeracją projektów `BUD-YYYY-NNN`.
- Timeline rezerwacji w stylu Gantt — siatka maszyna × dni.
- Panel administracyjny w Django (motyw Tailwind przez `django-unfold`).
- Audit trail (`django-simple-history`) dla każdego modelu.

## Stack technologiczny

| Warstwa | Technologia |
|---------|-------------|
| Runtime | Python 3.14 |
| Framework | Django 5.2 LTS |
| Package manager | uv |
| Baza danych | PostgreSQL 16 (via Docker / OrbStack) |
| Frontend | HTMX 2 + Alpine.js 3 + Tailwind CSS 3 (vendored, zero CDN) |
| Date picker | Flatpickr (z polską lokalizacją) |
| Admin theme | django-unfold |
| Audit trail | django-simple-history |
| Security | django-axes (brute-force) + django-csp (CSP headers) |
| Testy | pytest-django + factory_boy + freezegun + hypothesis |
| Linter / formatter | ruff |

Pełna lista i wersje: zobacz `pyproject.toml` (po inicjalizacji Django).

## Uruchomienie (po zakończeniu Milestone 2)

```bash
# Wymagania: Python 3.14, uv, Docker (lub OrbStack na macOS)

uv sync                                  # instaluje zależności
docker-compose up -d                     # startuje PostgreSQL 16
cp .env.example .env                     # konfiguracja lokalna
uv run python manage.py migrate          # tworzy schemat bazy
uv run python manage.py createsuperuser  # konto admina
uv run python manage.py seed_demo        # demo data (maszyny, budowy, rezerwacje)
uv run python manage.py runserver        # http://localhost:8000
```

## Testy

```bash
uv run pytest -q                         # wszystkie testy
uv run pytest --cov                      # z coverage (target ≥ 80%)
uv run ruff check . && uv run ruff format --check .
```

## Struktura projektu (target po M2)

```
planer-maszyn/
├── archive/milestone-1/      # zachowany kod M1 (console app, 175 testów)
├── planer_config/            # Django project (settings, urls, wsgi)
├── machines/                 # app: maszyny, statusy, przeglądy
├── reservations/             # app: rezerwacje + budowy + has_conflict
├── service/                  # app: ServiceRecord + bulk inspection
├── core/                     # shared: utils, mixins, base templates
├── templates/                # Django templates (base.html + per-app)
├── static/vendor/            # HTMX, Alpine, Tailwind, Flatpickr (vendored)
├── tests/                    # pytest-django: unit + integration + e2e
├── docker-compose.yml        # PostgreSQL 16 dla dev
├── .env.example              # template konfiguracji
└── pyproject.toml            # Django + uv + ruff + pytest stack
```

## Milestone 1 (zarchiwizowane)

Aplikacja konsolowa zakończona 12.04.2026 — 175 testów PASS, 20 maszyn demo,
33 rezerwacje, 150+ wpisów serwisowych. Cały kod + testy + dane demo dostępne
w [`archive/milestone-1/`](archive/milestone-1/) jako materiał referencyjny
i baza do migracji danych.

Najważniejsze elementy biznesowe z M1 zachowane w M2:

- **Statusy maszyn:** `W magazynie`, `Na budowie`, `Zarezerwowana`, `W serwisie`.
- **Statusy rezerwacji:** `oczekująca`, `potwierdzona`, `anulowana`, `zakończona`.
- **Hard Return Policy** — przeterminowana rezerwacja przedłużana do dnia
  zwrotu zamiast automatycznego zamykania (zapobiega "gubieniu" maszyn).
- **Walidacja konfliktów** — stykające się daty traktowane jako konflikt
  (maszyna potrzebuje dnia na transport).

## Dokumenty planistyczne

- [`JIRA_TASKS_Milestone2.md`](JIRA_TASKS_Milestone2.md) — pełny plan M2 (8 sprintów).
- [`NOTES_FOR_MILESTONE_3.md`](NOTES_FOR_MILESTONE_3.md) — propozycje dla M3 (i18n,
  RBAC, mailing, deployment, raporty, opcjonalne integracje).

## Licencja

GPL-3.0-or-later — patrz [`LICENSE`](LICENSE).
