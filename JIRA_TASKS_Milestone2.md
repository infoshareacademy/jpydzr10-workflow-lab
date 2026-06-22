# JIRA Tasks — Milestone 2: Aplikacja Web (Django)

**Projekt:** Planer Maszyn Budowlanych — system rezerwacji i serwisu maszyn dla firmy **BudMech**.
**Milestone 1 (Aplikacja konsolowa):** zakończony 12.04.2026, 175 testów, 20 maszyn demo, 33 rezerwacje, 150+ wpisów serwisowych.
**Milestone 2 (Aplikacja web — Django):** rozpoczyna się **20.04.2026**, deadline prezentacji **14.06.2026** (8 tygodni).
**Milestone 3 (Aplikacja web zaawansowana):** 15.06 → 09.08.2026 (propozycje w `NOTES_FOR_MILESTONE_3.md`).

---

## Cel Milestone 2

Cała funkcjonalność aplikacji konsolowej przeniesiona na interfejs webowy w Django, z dojrzałym stackiem produkcyjnym (PostgreSQL, HTMX, Alpine.js, Tailwind, Flatpickr, django-unfold admin, simple-history audit, django-axes security), pełnym pokryciem testowym (pytest-django + factory_boy + freezegun + hypothesis + playwright), oraz panelu administracyjnego — wszystko po polsku, gotowe na prezentację.

Z oryginalnego harmonogramu Milestone 2 obejmuje:

- Interfejs webowy
- Przeniesienie funkcjonalności do web
- Konfiguracja bazy danych
- Wczytywanie danych z bazy danych
- Panel administratora

Ten plan rozszerza ten zakres o dojrzały stack, refaktor UI na wzorzec Alpine Reactive Derived UI State, timeline rezerwacji w stylu „Lamborgini" oraz kompletne testy integracyjne i E2E.

---

## Konwencje i bezwzględne zasady

- **Język UI:** 100% polski. Zero angielskich/niderlandzkich/francuskich stringów w Milestone 2. Internacjonalizacja (PL/NL/FR/EN) wchodzi w Milestone 3.
- **Język kodu:** angielski (nazwy klas, funkcji, zmiennych, komentarzy, docstringów). Wyjątek: nazwy domenowe biznesowe (`BudowaManager` → preferuj `ConstructionSiteManager`).
- **Git workflow:** `feature/m2-sN-<nazwa>` branche → rebase na develop → squash merge do develop → sprint end: develop → main z merge commit.
- **Commit messages:** `typ: opis` (np. `feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`, `style:`). Bez `--amend` (chyba że Sebastian wyraźnie poprosi), bez `--no-verify`.
- **Każdy commit:** wszystkie testy zielone (`uv run pytest -q`), lint czysty (`uv run ruff check .` + `uv run ruff format --check .`).
- **Każdy merge do develop:** + test coverage ≥ 80%, + manualna weryfikacja UI w przeglądarce dla widoków (HTMX/Alpine).
- **Baza danych:** **wyłącznie PostgreSQL** (16 lub 18) via OrbStack Docker. Nigdy SQLite, nawet w testach.
- **Python + deps:** `uv` jako package manager + venv. `ruff` jako linter+formatter. `pre-commit` hook wymuszany.
- **Magic numbers / strings:** wszystkie w module-level constants.
- **`except Exception` zakazane** — konkretne wyjątki lub komentarz wyjaśniający.
- **TODO zakazane w kodzie** (wszystkie TODO z M1 muszą być zamienione na taski w tym dokumencie lub w kodzie jako `raise NotImplementedError` dla przyszłych feature'ów).

---

## Stack technologiczny M2 (wersje zweryfikowane 2026-04-20)

### Runtime + framework

| Warstwa | Technologia | Wersja | Pin w `pyproject.toml` |
|---------|------------|--------|------------------------|
| Python | CPython | **3.14.4** (najnowszy stable, EOL 2030) | `requires-python = ">=3.14"` |
| Package manager | **uv** | **0.11.7** | narzędzie, nie w deps |
| Web framework | **Django LTS** | **5.2.13** (LTS do 2028-04-30) | `django>=5.2,<5.3` |
| DB driver | **psycopg[binary]** | **3.3.3** | `psycopg[binary]>=3.3` |
| DB server | PostgreSQL | **16** (stable do 2028-11, rekomendowany) lub **18** (najnowszy, do 2030-11) | via OrbStack image |

### Frontend (zero CDN, wszystko vendored w `static/vendor/`)

| Biblioteka | Wersja | Plik |
|------------|--------|------|
| **HTMX** | **2.0.9** | `htmx.min.js` |
| HTMX ext: `loading-states` | latest | `htmx-ext-loading-states.js` |
| HTMX ext: `response-targets` | latest | `htmx-ext-response-targets.js` |
| **Alpine.js** | **3.15.11** | `alpine.min.js` |
| Alpine plugin: `persist` | latest | `alpine-persist.js` |
| Alpine plugin: `focus` | latest | `alpine-focus.js` |
| Alpine plugin: `mask` | latest | `alpine-mask.js` |
| **Tailwind CSS** | **3.4.19** (stabilna, Active) | `tailwind.min.css` (build z `input.css`) |
| **Flatpickr** | **4.6.13** + `flatpickr-pl.js` | `flatpickr.min.js` + `flatpickr-pl.js` + `flatpickr.min.css` |
| Heroicons | v2 (inline SVG w szablonach) | n/d — copy-paste |
| Inter font | v4 (woff2, Latin subset) | `static/fonts/Inter-*.woff2` |
| JetBrains Mono (opcjonalnie, dla UID) | latest | `static/fonts/JetBrainsMono-*.woff2` |

### Django packages (production)

| Pakiet | Wersja | Zastosowanie |
|--------|--------|--------------|
| **django-simple-history** | **3.11.0** | Audit trail per model (`history = HistoricalRecords()`) |
| **django-unfold** | **0.90.0** | Nowoczesny Tailwind admin theme |
| **django-axes** | **8.3.1** | Brute-force login protection |
| **django-csp** | **4.0** | Content Security Policy headers |
| **django-htmx** | **1.27.0** | `request.htmx` helper + HX-* header shortcuts |
| **Pillow** | **12.2.0** | Upload zdjęć maszyn |
| **openpyxl** | **3.1.5** | Excel import/export w adminie |
| **python-dotenv** | **1.2.2** | `.env` loader |
| **python-dateutil** | **2.9.0** | `relativedelta(months=N)` dla `calculate_next_inspection` |
| **whitenoise** | **6.12.0** | Static serving (M3 prod) |
| **gunicorn** | **25.3.0** | WSGI server (M3 prod) |

### Dev / testing

| Pakiet | Wersja | Zastosowanie |
|--------|--------|--------------|
| **ruff** | **0.15.11** | Linter + formatter |
| **pre-commit** | **4.5.1** | Hook manager |
| **pytest** | **9.0.3** | Runner |
| **pytest-django** | **4.11.1** | Django integration |
| **pytest-cov** | **7.1.0** | Coverage, target ≥ 80% branch |
| **factory_boy** | **3.3.3** | Test fixtures |
| **freezegun** | **1.5.5** | `date.today()` mocking dla Hard Return Policy |
| **hypothesis** | **6.152.1** | Property-based testing dla `has_conflict`, `run_daily_sync` |
| **pytest-xdist** | **3.8.0** | Parallel test execution (`pytest -n auto`) |
| **pytest-bdd** | **8.1.0** | Given/When/Then scenariusze biznesowe |
| **playwright** + **pytest-playwright** | **1.58.0** + **0.7.2** | E2E browser testy (timeline, modal edit) |

### Środowisko dev (zewnętrzne, macOS-only)

- **OrbStack** — Docker runtime (zamiast Docker Desktop, szybszy, lżejszy).
- **TablePlus** — klient DB (opcjonalnie).
- **VSCode** lub **PyCharm** — IDE.

---

## Architektura projektu (target struktury po Milestone 2)

```
planer-maszyn/                              # root = nowy Django project (po archiwizacji M1)
├── archive/
│   └── milestone-1/
│       ├── console/                        # cały kod M1 (main.py, ui.py, logic.py, models.py, datastore.py, utils.py, exceptions.py, conftest.py, test_*.py, machines_db.json, data/)
│       └── JIRA_TASKS_Milestone1.md        # (jeśli zostanie zresurrect — obecnie nie ma)
├── planer/                                 # Django project config
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py                             # Root URL
│   ├── asgi.py
│   ├── wsgi.py
│   ├── constants.py                        # MONTHS_PL, STATUS_COLORS, STATUS_ICONS
│   └── views.py                            # home (redirect to dashboard), healthz
├── machines/                               # App: inwentarz maszyn
│   ├── __init__.py
│   ├── apps.py
│   ├── admin.py                            # MachineAdmin, EmployeeProfileAdmin
│   ├── models.py                           # Machine, EmployeeProfile (jeśli M2)
│   ├── services.py                         # create_machine, update_machine, set_machine_service, return_machine
│   ├── views.py                            # machine_list, machine_detail, dashboard, timeline, machine_create, machine_edit, status_sync
│   ├── forms.py                            # MachineForm
│   ├── urls.py
│   ├── migrations/
│   │   ├── 0001_initial.py                 # Machine model
│   │   └── 0002_seed_machines_from_m1.py   # Data migration z archive JSON
│   └── management/
│       └── commands/
│           └── seed_all.py                 # Maszyny + rezerwacje + serwis + user demo
├── reservations/                           # App: rezerwacje + budowy
│   ├── models.py                           # Reservation, ConstructionSite (TASK 14 z M1 v2!)
│   ├── services.py                         # has_conflict, run_daily_sync, create_reservation, update_reservation, cancel_reservation, complete_reservation, create_site, update_site
│   ├── views.py                            # reservation_list/create/edit/cancel/complete, site_list/create/edit, timeline modal endpoints
│   ├── forms.py                            # ReservationForm, ConstructionSiteForm
│   └── migrations/
├── service/                                # App: serwis (przeglądy + naprawy)
│   ├── models.py                           # ServiceRecord (DecimalField cost + relativedelta calc)
│   ├── services.py                         # add_service_record, update_service_record
│   ├── views.py                            # service_history, service_add, bulk_inspection, service_export_csv, service_record_modal
│   └── forms.py                            # ServiceRecordForm
├── templates/
│   ├── base.html                           # HTMX + Alpine + Tailwind + Flatpickr includes, FOUC theme prevention
│   ├── dashboard.html                      # KPI cards + timeline embed
│   ├── machines/
│   │   ├── machine_list.html
│   │   ├── _machine_table.html             # HTMX partial
│   │   ├── machine_detail.html
│   │   ├── machine_form.html
│   │   ├── timeline.html                   # standalone view (redirect do dashboardu)
│   │   ├── _timeline_grid.html             # HTMX partial (Alpine reactive w Sprint 6)
│   │   └── _edit_modal.html
│   ├── reservations/
│   │   ├── reservation_list.html
│   │   ├── _reservation_table.html
│   │   ├── reservation_detail.html
│   │   ├── reservation_form.html
│   │   ├── _reservation_modal.html         # HTMX/Alpine modal
│   │   ├── site_list.html
│   │   ├── site_detail.html
│   │   ├── site_form.html
│   │   └── _site_create_inline.html
│   ├── service/
│   │   ├── service_history.html
│   │   ├── _service_table.html
│   │   ├── service_form.html
│   │   ├── bulk_inspection.html
│   │   └── _service_record_modal.html
│   └── components/
│       ├── _toast.html                     # Alpine-based toast system
│       ├── _skeleton_loader.html
│       └── _empty_state.html
├── static/
│   ├── vendor/                             # zero CDN
│   │   ├── htmx.min.js
│   │   ├── htmx-ext-loading-states.js
│   │   ├── htmx-ext-response-targets.js
│   │   ├── alpine.min.js
│   │   ├── alpine-persist.js
│   │   ├── alpine-focus.js
│   │   ├── alpine-mask.js
│   │   ├── tailwind.min.css                # pre-built
│   │   ├── flatpickr.min.js
│   │   ├── flatpickr.min.css
│   │   └── flatpickr-pl.js
│   ├── css/
│   │   ├── input.css                       # Tailwind source
│   │   └── theme.css                       # CSS custom properties (dark mode)
│   └── fonts/
│       ├── Inter-Variable.woff2
│       └── JetBrainsMono-Variable.woff2    # opcjonalnie
├── media/                                  # user uploads (machines/, inspections/)
├── tests/
│   ├── conftest.py                         # fixtures, pytest_plugins
│   ├── factories/
│   │   ├── __init__.py
│   │   ├── machine.py
│   │   ├── reservation.py
│   │   ├── service_record.py
│   │   └── construction_site.py
│   ├── unit/
│   │   ├── test_machine_model.py
│   │   ├── test_reservation_model.py
│   │   ├── test_service_record_model.py
│   │   ├── test_construction_site_model.py
│   │   ├── test_conflict_detection.py     # + hypothesis
│   │   └── test_daily_sync.py             # + freezegun
│   ├── integration/
│   │   ├── test_machine_views.py
│   │   ├── test_reservation_flow.py
│   │   ├── test_service_flow.py
│   │   ├── test_timeline_view.py           # HTMX partials, filters, nav
│   │   └── test_admin_bulk_import.py
│   ├── e2e/
│   │   ├── test_playwright_reservation_create.py
│   │   └── test_playwright_timeline_modal.py
│   └── bdd/
│       ├── reservations.feature            # Gherkin scenariusze
│       └── steps_reservations.py
├── .env                                    # gitignored, local secrets
├── .env.example                            # commitowane, szablon
├── .github/
│   └── workflows/
│       └── ci.yml                          # lint + test + coverage gate
├── .pre-commit-config.yaml                 # ruff + uv lock check + pytest fast
├── docker-compose.yml                      # PostgreSQL 16 service
├── Dockerfile                              # (M3 deploy)
├── pyproject.toml                          # uv deps + ruff + pytest + coverage config
├── uv.lock
├── manage.py
├── tailwind.config.js                      # Tailwind source config
├── JIRA_TASKS_Milestone2.md                # ten plik (public)
├── NOTES_FOR_MILESTONE_3.md                # public
├── README.md                               # update po M2
└── LICENSE
```

---

## Harmonogram sprintów

**8 tygodni × 7 dni = 56 dni. 7 sprintów rozwoju (S1–S7) + 1 sprint testowania (S8).**

| Sprint | Daty | Cel (tytuł) | Główne deliverables |
|--------|------|-------------|---------------------|
| **S1** | 20.04 – 26.04 | Fundament Django | Django 5.2 project + uv + PostgreSQL Docker + pre-commit + base template + admin |
| **S2** | 27.04 – 03.05 | Model maszyn + import | App `machines` + model + migracja seed + admin CRUD + views list/detail |
| **S3** | 04.05 – 10.05 | Rezerwacje + budowy + konflikty | App `reservations` + modele Reservation + ConstructionSite + has_conflict + daily_sync |
| **S4** | 11.05 – 17.05 | Serwis + Decimal + dateutil | App `service` + ServiceRecord (DecimalField) + bulk inspection + CSV export |
| **S5** | 18.05 – 24.05 | Timeline skeleton + filtry + nawigacja | CSS Grid timeline + sticky controls + filter popover + pending banner + overdue alert |
| **S6** | 25.05 – 31.05 | Alpine Reactive Refactor | Timeline + modal edit w pełni reactive (Opcja B pattern) |
| **S7** | 01.06 – 07.06 | Admin Dashboard polish + bulk import + UI polish | Dashboard KPI + bulk CSV import + dark mode + Heroicons + glass-morphism + toasty |
| **S8** | 08.06 – 14.06 | **Testing week** — tylko testy + bugfixy + prezentacja | Pełne pokrycie testowe, zero nowych feature'ów |

**Aplikacja musi być w pełni funkcjonalna do końca S7 (07.06).** S8 to wyłącznie testy, bugfixy i polish prezentacyjny.

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ ⚡ SPRINT 1 (20.04 – 26.04) ─── Fundament Django ⚡                ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** Przekształcenie repozytorium konsolowego w profesjonalny Django 5.2 project z pełnym dojrzałym stackiem. Środowisko dev + CI-ready.

**Branch:** `feature/m2-s1-fundament`

## Taski

### S1-T01 — Archiwizacja Milestone 1

Przenieś cały kod konsolowy do `archive/milestone-1/console/`:

- `main.py`, `ui.py`, `logic.py`, `models.py`, `datastore.py`, `utils.py`, `exceptions.py`, `conftest.py`
- `test_models.py`, `test_logic.py`, `test_utils_and_datastore.py`, `test_integration.py`, `test_demo_data.py`
- `machines_db.json`
- `data/machines.json`, `data/reservations.json`, `data/service_records.json`
- `pyproject.toml`, `uv.lock` (tymczasowo — będą odtworzone dla Django w S1-T03)

Zostają w root: `.gitignore`, `.pre-commit-config.yaml` (jeśli istnieje), `LICENSE`, `README.md` (zostanie przepisany w S1-T14).

**Acceptance Criteria:**
- Katalog `archive/milestone-1/console/` zawiera wszystkie pliki M1 wymienione powyżej.
- Root nie zawiera plików M1 poza README/LICENSE/.gitignore.
- `git log` pokazuje commit `chore: archive milestone 1 console app`.

---

### S1-T02 — Inicjalizacja Django 5.2 LTS project przez uv

```bash
uv init --package planer-maszyn
uv add 'django>=5.2,<5.3'
uv run django-admin startproject planer .
```

- Project structure: `planer/` (settings + urls + wsgi + asgi) + `manage.py` w root.
- Pierwszy `runserver` musi zadziałać (Welcome page).

**Acceptance Criteria:**
- `uv run python manage.py runserver` pokazuje Django welcome page.
- `uv run python manage.py check` — zero błędów.
- `pyproject.toml` zawiera `django>=5.2,<5.3` w `[project.dependencies]`.

---

### S1-T03 — pyproject.toml: pełne deps + tool configs

Dodaj wszystkie pakiety produkcyjne + dev:

```toml
[project]
name = "planer-maszyn"
version = "2.0.0"                       # M2 major bump
description = "Planer Maszyn Budowlanych — system rezerwacji maszyn dla BudMech"
readme = "README.md"
license = "GPL-3.0-or-later"
requires-python = ">=3.14"
authors = [
    { name = "Sebastian", email = "kontakt@budmech.pl" },
]
dependencies = [
    "django>=5.2,<5.3",
    "psycopg[binary]>=3.3",
    "django-simple-history>=3.11",
    "django-unfold>=0.90",
    "django-axes>=8.3",
    "django-csp>=4.0",
    "django-htmx>=1.27",
    "Pillow>=12.2",
    "openpyxl>=3.1",
    "python-dotenv>=1.2",
    "python-dateutil>=2.9",
    "whitenoise>=6.12",
]

[dependency-groups]
dev = [
    "ruff>=0.15",
    "pre-commit>=4.5",
    "pytest>=9.0",
    "pytest-django>=4.11",
    "pytest-cov>=7.1",
    "factory-boy>=3.3",
    "freezegun>=1.5",
    "hypothesis>=6.152",
    "pytest-xdist>=3.8",
    "pytest-bdd>=8.1",
    "pytest-playwright>=0.7",
    "django-debug-toolbar>=5.0",
]
prod = [
    "gunicorn>=25.3",
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "planer.settings.dev"
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-v --tb=short --cov=. --cov-report=term-missing --cov-report=html"

[tool.coverage.run]
source = ["machines", "reservations", "service", "planer"]
omit = ["*/migrations/*", "*/tests/*", "manage.py", "planer/settings/*"]
branch = true

[tool.coverage.report]
fail_under = 80
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]

[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP", "B", "SIM", "RUF", "DJ"]
ignore = ["E501", "SIM108"]

[tool.ruff.lint.per-file-ignores]
"*/migrations/*" = ["E501", "N806"]
"tests/*" = ["N802", "N803"]
```

**Acceptance Criteria:**
- `uv sync` działa bez błędów.
- `uv run pytest --collect-only` znajduje pliki testowe.
- `uv run ruff check .` — zero naruszeń (pusty projekt).

---

### S1-T04 — Docker Compose z PostgreSQL 16 + OrbStack

Plik `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: planer_maszyn
      POSTGRES_USER: planer
      POSTGRES_PASSWORD: planer_dev_2026
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U planer -d planer_maszyn"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

Dokumentacja w `README.md` jak uruchomić: `docker compose up -d` + sprawdzenie logami.

**Acceptance Criteria:**
- `docker compose up -d` startuje kontener postgres.
- `docker compose ps` pokazuje status `healthy`.
- Z TablePlus można się połączyć na `localhost:5432` z kredencjałami.

---

### S1-T05 — Django settings split (base/dev/prod)

Struktura:

```
planer/
  settings/
    __init__.py    # pusty
    base.py        # wspólne: INSTALLED_APPS, MIDDLEWARE, DATABASES, AUTH, TEMPLATES, STATIC
    dev.py         # from .base import *; DEBUG=True; Debug Toolbar
    prod.py        # from .base import *; DEBUG=False; SECURE_*
```

- `DATABASES`: `psycopg` (v3) + env vars (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`).
- `INSTALLED_APPS`: `unfold` (PRZED `django.contrib.admin`!), `django.contrib.admin`, `django.contrib.auth`, `django.contrib.contenttypes`, `django.contrib.sessions`, `django.contrib.messages`, `django.contrib.staticfiles`, `simple_history`, `django_htmx`, `axes`, `csp`.
- `MIDDLEWARE`: security first, then `simple_history.middleware.HistoryRequestMiddleware`, `django_htmx.middleware.HtmxMiddleware`, `axes.middleware.AxesMiddleware`, `csp.middleware.CSPMiddleware`.
- Custom `TEMPLATES` → `context_processors`: add `planer.context_processors.theme_preference`.
- `STATIC_URL = "/static/"`, `STATICFILES_DIRS = [BASE_DIR / "static"]`, `STATIC_ROOT = BASE_DIR / "staticfiles"`.
- `MEDIA_URL = "/media/"`, `MEDIA_ROOT = BASE_DIR / "media"`, `FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024`.
- `LANGUAGE_CODE = "pl"`, `TIME_ZONE = "Europe/Warsaw"`, `USE_I18N = True`, `USE_TZ = True`.

**Acceptance Criteria:**
- `DJANGO_SETTINGS_MODULE=planer.settings.dev uv run python manage.py migrate` działa.
- Pierwsze uruchomienie tworzy wszystkie tabele Django + simple_history + axes w PostgreSQL.

---

### S1-T06 — .env + .env.example + python-dotenv

Plik `.env` (gitignored):

```
DEBUG=True
SECRET_KEY=<wygenerowany>
POSTGRES_DB=planer_maszyn
POSTGRES_USER=planer
POSTGRES_PASSWORD=planer_dev_2026
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
DJANGO_SETTINGS_MODULE=planer.settings.dev
```

Plik `.env.example` (commitowany): to samo ale z placeholderami.

W `planer/settings/base.py`:

```python
from pathlib import Path
import dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
dotenv.load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ["SECRET_KEY"]
```

**Acceptance Criteria:**
- `.env` jest w `.gitignore`.
- `.env.example` zawiera wszystkie klucze bez wartości.
- Dev server czyta konfig z .env.

---

### S1-T07 — base.html template (HTMX + Alpine + Tailwind + Flatpickr + FOUC prevention)

Struktura `templates/base.html`:

- `<head>`: meta, title (block), **FOUC prevention script** (inline, synchroniczne czytanie theme z localStorage PRZED pierwszym paint — ze sprawdzonego wzorca), `{% static "vendor/tailwind.min.css" %}`, `{% static "vendor/flatpickr.min.css" %}`, CSS vars theme.
- `<body>`: nav, main (block content), footer, toast container.
- `<script>` na końcu `<body>`: `htmx.min.js`, htmx-ext-loading-states, htmx-ext-response-targets, `alpine-persist.js` (PRZED alpine), `alpine-focus.js`, `alpine-mask.js`, `alpine.min.js`, `flatpickr.min.js`, `flatpickr-pl.js`, `flatpickr.localize(window.flatpickr.l10ns.pl)`.

**CSS FOUC prevention:**

```html
<script>
(function() {
  const stored = localStorage.getItem('theme') || 'auto';
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const effective = stored === 'auto' ? (prefersDark ? 'dark' : 'light') : stored;
  document.documentElement.classList.add('theme-' + effective);
})();
</script>
<style>[x-cloak] { display: none !important; }</style>
```

**Acceptance Criteria:**
- HTMX, Alpine, Tailwind, Flatpickr ładują się z `static/vendor/` (nie CDN).
- `[x-cloak]` globalny.
- FOUC prevention działa (nie ma „błysku" motywu przy reload).
- Flatpickr pokazuje polski kalendarz (sprawdź ręcznie).

---

### S1-T08 — Pre-commit hook (.pre-commit-config.yaml)

```yaml
repos:
  - repo: https://github.com/astral-sh/uv-pre-commit
    rev: 0.11.7
    hooks:
      - id: uv-lock                    # sprawdza czy uv.lock jest up-to-date

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.11
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format

  - repo: local
    hooks:
      - id: pytest-fast
        name: pytest fast (no slow/e2e marks)
        entry: uv run pytest -q -m "not slow and not e2e"
        language: system
        pass_filenames: false
        stages: [pre-commit]
```

Instalacja: `uv run pre-commit install`.

**Acceptance Criteria:**
- `git commit` z nieformatowanymi plikami — hook auto-formatuje i blokuje commit (user musi `git add` ponownie).
- Niedziałające testy szybkie blokują commit.
- `uv.lock` niezgodny z `pyproject.toml` blokuje commit.

---

### S1-T09 — Django admin: django-unfold setup

- `INSTALLED_APPS`: `"unfold"` **przed** `"django.contrib.admin"`.
- Custom `UNFOLD` dict w `settings/base.py` — branding "Planer Maszyn", kolory, shortcuts.
- `planer/admin_dashboard.py` — zaplanowane w S7, na razie stub.
- Pierwszy superuser: `uv run python manage.py createsuperuser` (lub w `seed_all` w S2).

**Acceptance Criteria:**
- `/admin/` pokazuje django-unfold UI (nie standardowy Django).
- Sidebar ma branding „Planer Maszyn".
- Logowanie działa (ze standardową Django auth + Axes w tle).

---

### S1-T10 — Security settings (axes + CSP + prod hardening)

`planer/settings/base.py` (fragmenty):

```python
# Axes
AXES_FAILURE_LIMIT = 6
AXES_COOLOFF_TIME = 1  # godzina
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# CSP
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "style-src": ["'self'", "'unsafe-inline'"],   # Tailwind + Alpine
        "script-src": ["'self'", "'unsafe-inline'"],  # HTMX + Alpine
        "img-src": ["'self'", "data:", "blob:"],
        "frame-ancestors": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
    },
}

# File upload
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
```

`planer/settings/prod.py`:

```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
```

**Acceptance Criteria:**
- 6 nieudanych prób logowania blokuje user+IP na godzinę (test manualny).
- Response ma header `Content-Security-Policy`.
- Prod settings (`DJANGO_SETTINGS_MODULE=planer.settings.prod`) mają HSTS + SSL redirect.

---

### S1-T11 — Tailwind build + input.css + theme tokens

`tailwind.config.js`:

```js
module.exports = {
  content: [
    "./templates/**/*.html",
    "./**/*.py",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#0d9488',  // teal-600 — brand
          dark: '#0f766e',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
```

`static/css/input.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import "./theme.css";

@font-face {
  font-family: 'Inter';
  src: url('/static/fonts/Inter-Variable.woff2') format('woff2');
  font-weight: 100 900;
  font-display: swap;
}
```

Build:

```bash
npx tailwindcss -i static/css/input.css -o static/vendor/tailwind.min.css --minify
```

Dodaj `npm`/`npx` do opisu w README (alternatywa: tailwindcss CLI standalone binary bez npm).

**Acceptance Criteria:**
- `static/vendor/tailwind.min.css` zbudowany po wywołaniu CLI.
- base.html + pierwszy widok używa klas Tailwind i renderuje się poprawnie.

---

### S1-T12 — Healthz endpoint + root URL + planer/views.py

`planer/views.py`:

```python
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

@never_cache
def healthz(request):
    """Liveness + DB ping. Używane przez monitoring prod."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error", "db": "down"}, status=503)
    return JsonResponse({"status": "ok", "db": "up"})


def home(request):
    """Root → dashboard (po zalogowaniu) lub login."""
    if request.user.is_authenticated:
        return redirect("machines:dashboard")
    return redirect("admin:login")
```

`planer/urls.py`:

```python
from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("admin/", admin.site.urls),
    # Apps dodawane w kolejnych sprintach:
    # path("machines/", include("machines.urls")),
    # path("reservations/", include("reservations.urls")),
    # path("service/", include("service.urls")),
]
```

**Acceptance Criteria:**
- `GET /healthz/` zwraca `{"status": "ok", "db": "up"}` gdy Postgres działa.
- `GET /healthz/` zwraca `503` gdy Postgres zatrzymany.
- `GET /` (niezalogowany) → redirect do `/admin/login/`.

---

### S1-T13 — .github/workflows/ci.yml baseline

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: planer_maszyn
          POSTGRES_USER: planer
          POSTGRES_PASSWORD: planer_dev_2026
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: "0.11.7"
      - run: uv sync --all-extras
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest -q
```

**Acceptance Criteria:**
- Push do gałęzi `feature/m2-s1-*` uruchamia CI.
- Wszystkie kroki green (pytest nic nie znajduje jeszcze = success).

---

### S1-T14 — README update: M2 edition

Przepisz `README.md`:

- Sekcja "Milestone 2 — Aplikacja web (Django)" — w trakcie rozwoju.
- Tech stack table (wersje z tego dokumentu).
- Quick start:
  ```bash
  git clone ...
  cd planer-maszyn
  cp .env.example .env && <edytuj>
  docker compose up -d
  uv sync
  uv run python manage.py migrate
  uv run python manage.py createsuperuser
  uv run python manage.py runserver
  ```
- Testy: `uv run pytest`.
- Link do `archive/milestone-1/` dla historii.

**Acceptance Criteria:**
- README krótki, aktualny, z instrukcją quick start.
- Sekcja M1 → `archive/milestone-1/README.md` (nowy plik z krótkim opisem co tam jest).

---

## Definition of Done Sprint 1

- [ ] Archive M1 code przeniesiony do `archive/milestone-1/console/`.
- [ ] Django 5.2 LTS project utworzony, runs bez błędu.
- [ ] `pyproject.toml` + `uv.lock` z pełnymi deps.
- [ ] PostgreSQL 16 uruchamia się via `docker compose up -d` + healthy.
- [ ] `uv run python manage.py migrate` przechodzi bez błędów — DB wszystkie tabele utworzone.
- [ ] `/admin/` pokazuje django-unfold UI + login działa.
- [ ] `GET /healthz/` zwraca JSON status.
- [ ] `base.html` z HTMX+Alpine+Tailwind+Flatpickr vendored (zero CDN).
- [ ] Pre-commit hook instalowany, blokuje commit przy ruff violation.
- [ ] CI uruchamia się na push, wszystkie kroki green.
- [ ] README zaktualizowane.
- [ ] `uv run ruff check .` — 0 naruszeń.
- [ ] `uv run ruff format --check .` — 0 diffów.
- [ ] `uv run pytest` — 0 testów (prawidłowo, bo jeszcze nic nie ma), exit 0.
- [ ] Merge `feature/m2-s1-fundament` → `develop` (rebase + fast-forward lub squash).

## Git flow Sprint 1 (komendy dla Sebastiana)

```bash
# 1. Start
git switch main && git pull --ff-only
git switch develop 2>/dev/null || git switch -c develop
git pull --ff-only 2>/dev/null || true
git switch -c feature/m2-s1-fundament

# 2. Praca — każdy task = 1-2 commity
git add -p && git commit -m "chore: archive milestone 1 console app"
git add pyproject.toml uv.lock && git commit -m "chore: init Django 5.2 project via uv"
# ... (pozostałe taski, każdy własny commit)

# 3. Przed push — rebase na develop
git fetch origin
git rebase origin/develop
# (jeśli konflikty: git add + git rebase --continue)
git push -u origin feature/m2-s1-fundament --force-with-lease

# 4. Merge do develop
git switch develop && git pull --ff-only
git merge --ff-only feature/m2-s1-fundament
# ALTERNATYWA: git merge --squash feature/m2-s1-fundament && git commit -m "feat: Sprint 1 Fundament (14 tasków)"
git push origin develop

# 5. Cleanup
git push origin --delete feature/m2-s1-fundament
git branch -d feature/m2-s1-fundament

# 6. (koniec wszystkich sprintów) develop → main z merge commit
#    → robimy to dopiero po S7 lub S8, nie teraz
```

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ 🏗️ SPRINT 2 (27.04 – 03.05) ─── Model maszyn + import 🏗️           ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** App `machines` z modelem Machine 1:1 z M1, admin CRUD z django-unfold, management command `seed_all`, pierwsze widoki list/detail/create/edit z HTMX, pełne pokrycie testowe.

**Branch:** `feature/m2-s2-machines-model`

## Taski

### S2-T01 — App `machines` + `apps.py` + rejestracja

```bash
uv run python manage.py startapp machines
```

`machines/apps.py`:

```python
class MachinesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "machines"
    verbose_name = "Maszyny budowlane"
```

Dodaj `"machines.apps.MachinesConfig"` do `INSTALLED_APPS`.

---

### S2-T02 — Model `Machine` (Django ORM)

`machines/models.py`:

```python
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords


class Machine(models.Model):
    class Status(models.TextChoices):
        W_MAGAZYNIE = "w_magazynie", "W magazynie"
        NA_BUDOWIE = "na_budowie", "Na budowie"
        ZAREZERWOWANA = "zarezerwowana", "Zarezerwowana"
        W_SERWISIE = "w_serwisie", "W serwisie"
        WYCOFANA = "wycofana", "Wycofana z eksploatacji"

    DEFAULT_LOCATION = "Magazyn"
    INSPECTION_WARNING_DAYS = 14

    uid = models.CharField("UID (firmowy)", max_length=20, unique=True, db_index=True,
                            help_text="Np. KOP-001")
    name = models.CharField("Nazwa", max_length=150)
    machine_type = models.CharField("Typ", max_length=60, db_index=True,
                                      help_text="Np. Koparka gąsienicowa, Ładowarka kołowa")
    model = models.CharField("Model", max_length=100, blank=True, default="")
    manufacturer = models.CharField("Producent", max_length=100, blank=True, default="")
    serial_number = models.CharField("Numer seryjny", max_length=100, blank=True, default="")
    build_year = models.PositiveIntegerField(
        "Rok produkcji", null=True, blank=True,
        validators=[MinValueValidator(1950), MaxValueValidator(2100)],
    )
    capacity = models.PositiveIntegerField("Nośność (kg)", default=0)
    inspection_date = models.DateField("Data następnego przeglądu", null=True, blank=True, db_index=True)
    location = models.CharField("Lokalizacja", max_length=300, default=DEFAULT_LOCATION)
    status = models.CharField("Status", max_length=20, choices=Status.choices,
                                default=Status.W_MAGAZYNIE, db_index=True)
    notes = models.TextField("Notatki", blank=True, default="")
    image = models.ImageField("Zdjęcie", upload_to="machines/", blank=True, null=True)

    created_at = models.DateTimeField("Utworzono", auto_now_add=True)
    updated_at = models.DateTimeField("Zaktualizowano", auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["uid"]
        verbose_name = "Maszyna"
        verbose_name_plural = "Maszyny"

    def __str__(self):
        return f"{self.uid} — {self.name}"

    @property
    def inspection_status(self) -> str:
        """Zwraca 'ok' / 'warning' (≤14 dni) / 'overdue'."""
        from datetime import date
        if not self.inspection_date:
            return "overdue"
        days_left = (self.inspection_date - date.today()).days
        if days_left < 0:
            return "overdue"
        if days_left <= self.INSPECTION_WARNING_DAYS:
            return "warning"
        return "ok"

    @property
    def is_available(self) -> bool:
        return self.status in (self.Status.W_MAGAZYNIE, self.Status.ZAREZEROWOWANA)  # typo protection test!
```

**Decyzja o wartościach enum:** M1 ma `"W magazynie"` (z dużej litery + spacja). Django TextChoices: **używamy snake_case dla `value`** (`"w_magazynie"`) i polski dla `label` (`"W magazynie"`). Dlaczego: convention Django, łatwiej w queryset filtrach, migracja danych M1 w S2-T04 mapuje wartości.

**Acceptance Criteria:**
- Migration `0001_initial` tworzy tabelę `machines_machine` + `machines_historicalmachine`.
- `Machine.objects.create(uid="KOP-001", ...)` działa.
- `Machine.Status.W_MAGAZYNIE` = `"w_magazynie"`, display = `"W magazynie"`.

---

### S2-T03 — Admin `MachineAdmin` z SimpleHistoryAdmin + unfold

```python
# machines/admin.py
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from .models import Machine


@admin.register(Machine)
class MachineAdmin(ModelAdmin, SimpleHistoryAdmin):
    list_display = ["uid", "name", "machine_type", "manufacturer", "status",
                     "location", "inspection_date", "inspection_status_icon"]
    list_filter = ["status", "machine_type", "manufacturer"]
    search_fields = ["uid", "name", "model", "serial_number", "manufacturer"]
    list_editable = ["status", "location"]
    list_per_page = 30
    ordering = ["uid"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = [
        ("Identyfikacja", {"fields": ["uid", "name", "machine_type", "model"]}),
        ("Szczegóły techniczne", {"fields": ["manufacturer", "serial_number",
                                                "build_year", "capacity", "image"]}),
        ("Status i lokalizacja", {"fields": ["status", "location"]}),
        ("Przegląd techniczny", {"fields": ["inspection_date"]}),
        ("Notatki", {"fields": ["notes"]}),
        ("Metadane", {"fields": ["created_at", "updated_at"], "classes": ["collapse"]}),
    ]

    @admin.display(description="Przegląd", ordering="inspection_date")
    def inspection_status_icon(self, obj):
        icons = {"ok": "✅", "warning": "⚠️", "overdue": "🔴"}
        return icons.get(obj.inspection_status, "?")
```

**Acceptance Criteria:**
- `/admin/machines/machine/` pokazuje tabelę z kolumnami + filtrami + search.
- Kliknięcie maszyny otwiera edycję z fieldsetami.
- Historia zmian widoczna w zakładce „History" (simple-history).

---

### S2-T04 — Management command `seed_all` (migracja danych z M1)

`machines/management/commands/seed_all.py` — czyta `archive/milestone-1/console/machines_db.json` (lub `data/machines.json`) i tworzy obiekty Machine. Mapuje `"W magazynie"` → `"w_magazynie"`. Opcja `--clear` czyści tabelę najpierw.

```python
class Command(BaseCommand):
    help = "Seed bazy demo danymi z Milestone 1."
    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--users", action="store_true", help="Tylko użytkownicy + grupy")
        parser.add_argument("--machines", action="store_true")
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **opts):
        if opts["clear"]:
            Machine.objects.all().delete()
        if opts["all"] or opts["users"]:
            self._seed_users()
        if opts["all"] or opts["machines"]:
            self._seed_machines()

    def _seed_users(self):
        from django.contrib.auth.models import Group, User
        admin_group, _ = Group.objects.get_or_create(name="admin")
        # + superuser Sebastian jeśli nie istnieje
        ...

    def _seed_machines(self):
        path = settings.BASE_DIR / "archive/milestone-1/console/machines_db.json"
        with open(path) as f:
            raw = json.load(f)
        status_map = {
            "W magazynie": Machine.Status.W_MAGAZYNIE,
            "Na budowie": Machine.Status.NA_BUDOWIE,
            "Zarezerwowana": Machine.Status.ZAREZEROWOWANA,
            "W serwisie": Machine.Status.W_SERWISIE,
        }
        for item in raw:
            Machine.objects.update_or_create(
                uid=item["uid"],
                defaults={
                    "name": item.get("name", ""),
                    "machine_type": item.get("type", ""),
                    # ... mapowanie camelCase → snake_case
                    "status": status_map[item["status"]],
                    # ...
                },
            )
```

**Acceptance Criteria:**
- `uv run python manage.py seed_all --machines` importuje 20 maszyn z JSON.
- `uv run python manage.py seed_all --clear --all` czyści i seeduje wszystko.
- Statusy poprawnie zmapowane (widoczne w admin).

---

### S2-T05 — App `machines` urls + views skeleton

`machines/urls.py`:

```python
from django.urls import path
from . import views

app_name = "machines"

urlpatterns = [
    path("", views.machine_list, name="list"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("create/", views.machine_create, name="create"),
    path("<int:pk>/", views.machine_detail, name="detail"),
    path("<int:pk>/edit/", views.machine_edit, name="edit"),
]
```

Views: `machine_list`, `machine_detail`, `machine_create`, `machine_edit`, `dashboard` (pełny w S5, teraz stub z count).

---

### S2-T06 — Service layer `machines/services.py`

```python
@transaction.atomic
def create_machine(uid, name, machine_type, ...) -> Machine:
    if not uid or not uid.strip():
        raise ValidationError("UID nie może być pusty.")
    m = Machine(uid=uid.strip().upper(), name=name.strip(), ...)
    m.full_clean()
    m.save()
    return m

@transaction.atomic
def update_machine(machine, **fields) -> list[str]:
    warnings = []
    if "status" in fields:
        # logika ostrzeżeń o desynchronizacji z rezerwacjami (standardowy pattern)
        ...
    for k, v in fields.items():
        setattr(machine, k, v)
    machine.full_clean()
    machine.save()
    return warnings
```

---

### S2-T07 — Forms (Django Forms + Tailwind class attrs)

`machines/forms.py`:

```python
from django import forms
from .models import Machine

TAILWIND_INPUT = "block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm"

class MachineForm(forms.ModelForm):
    class Meta:
        model = Machine
        fields = ["uid", "name", "machine_type", "model", "manufacturer", ...]
        widgets = {
            "uid": forms.TextInput(attrs={"class": TAILWIND_INPUT, "placeholder": "KOP-001"}),
            "inspection_date": forms.DateInput(attrs={"class": TAILWIND_INPUT, "type": "date"}),
            # ...
        }
```

---

### S2-T08 — Template `machine_list.html` + `_machine_table.html` (HTMX partial)

- Filtry: status, type, search (query param).
- HTMX `hx-get + hx-target + hx-push-url` dla page changes bez reload.
- Paginator 50 per page.
- Inspection icons w row.

---

### S2-T09 — Template `machine_detail.html`

- Pełne info maszyny.
- Sekcja "Ostatnie rezerwacje" + "Ostatnie wpisy serwisowe" (placeholder, modele w S3/S4).
- Przyciski edit / set_service / return / close_repair (action buttons).

---

### S2-T10 — Template `machine_form.html` (create + edit)

- DRY template dla create+edit.
- Flatpickr na `inspection_date`.
- Walidacja inline.

---

### S2-T11 — Tests Machine model (unit)

`tests/unit/test_machine_model.py` — portowanie z M1 `test_models.py` na pytest-django:

- All statuses accepted
- Empty UID raises
- Whitespace UID raises
- `inspection_status` (ok/warning/overdue, z freezegun dla boundary)
- `from_dict` → `to_dict` roundtrip (jeśli zachowujemy — raczej nie, Django ma serializers)
- Unicode in name
- `is_available` property

**factory_boy:**

```python
# tests/factories/machine.py
import factory
from machines.models import Machine

class MachineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Machine
    uid = factory.Sequence(lambda n: f"TST-{n:03d}")
    name = factory.Faker("catch_phrase", locale="pl_PL")
    machine_type = "Koparka"
    status = Machine.Status.W_MAGAZYNIE

class AvailableMachineFactory(MachineFactory):
    status = Machine.Status.W_MAGAZYNIE

class OnSiteMachineFactory(MachineFactory):
    status = Machine.Status.NA_BUDOWIE
    location = factory.Faker("street_address", locale="pl_PL")

class InServiceMachineFactory(MachineFactory):
    status = Machine.Status.W_SERWISIE
```

---

### S2-T12 — Tests integration (views)

`tests/integration/test_machine_views.py`:

- `test_machine_list_displays_all_machines`
- `test_machine_list_filter_by_status` (HTMX `HX-Request` header)
- `test_machine_list_search_by_uid`
- `test_machine_create_post_valid` (redirect po success, message flash)
- `test_machine_create_post_invalid` (form errors)
- `test_machine_edit_preserves_unchanged_fields`
- `test_machine_detail_displays_history` (simple-history tab)

---

### S2-T13 — Fix pyproject.toml bug: `planer = "main:main"`

W M1 był bug: `[project.scripts] planer = "main:main"` ale `main.py` nie miał `def main()`. W M2 console app jest zarchiwizowany, więc:

- Albo **usuń** całą sekcję `[project.scripts]` (Django nie potrzebuje CLI entry point).
- Albo **dodaj** `planer = "planer.manage:main"` jako alias do `manage.py` CLI.

Rekomendacja: **usuń sekcję** — `manage.py` w root wystarczy.

**Acceptance Criteria:**
- `uv sync` nie daje ostrzeżenia o script entry point.

---

### S2-T14 — Tailwind build dla machine list + detail (CSS + komponenty)

Zbuduj Tailwind po dodaniu nowych templates: `npx tailwindcss -i static/css/input.css -o static/vendor/tailwind.min.css --minify`. Upewnij się że `content:` w config łapie nowe pliki.

## DoD Sprint 2

- [ ] App `machines` utworzona i zarejestrowana.
- [ ] Model `Machine` z TextChoices + history + validators.
- [ ] Migracja `0001_initial` + (opcjonalnie) data migration z M1 JSON.
- [ ] `seed_all` command działa dla maszyn.
- [ ] `/admin/machines/machine/` pełny CRUD z unfold + history.
- [ ] `/machines/` pokazuje listę z filtrami + HTMX.
- [ ] `/machines/<pk>/` pokazuje detail.
- [ ] Create/Edit formy z Tailwind.
- [ ] 30+ testów (unit + integration) green.
- [ ] Coverage ≥ 75% dla `machines/` (docelowe 80% osiągnięte po S3-S4).
- [ ] pyproject.toml bug `planer = "main:main"` naprawiony.
- [ ] Merge `feature/m2-s2-machines-model` → `develop`.

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ 📋 SPRINT 3 (04.05 – 10.05) ─── Rezerwacje + Budowy + Konflikty 📋 ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** App `reservations` z modelami `Reservation` + `ConstructionSite` (nowy model, spełnia TASK 14 z M1 v2 który nigdy nie został zaimplementowany w M1), logika konfliktu i daily sync, pełny CRUD z HTMX modalami.

**Branch:** `feature/m2-s3-reservations`

## Taski

### S3-T01 — App `reservations` + urls skeleton

---

### S3-T02 — Model `ConstructionSite` (TASK 14 z M1 v2 — nigdy nie zaimplementowane)

```python
class ConstructionSite(models.Model):
    class Status(models.TextChoices):
        AKTYWNA = "aktywna", "Aktywna"
        ZAKONCZONA = "zakonczona", "Zakończona"
        ANULOWANA = "anulowana", "Anulowana"

    project_number = models.CharField("Numer projektu", max_length=20, unique=True, db_index=True,
                                        validators=[RegexValidator(r"^BUD-\d{4}-\d{3}$", "Format: BUD-YYYY-NNN")])
    site_name = models.CharField("Nazwa budowy", max_length=200)
    client_name = models.CharField("Klient", max_length=200)
    project_manager = models.CharField("Kierownik projektu", max_length=100, blank=True, default="")
    foreman = models.CharField("Brygadzista", max_length=100, blank=True, default="")
    address = models.CharField("Adres", max_length=300)
    status = models.CharField(choices=Status.choices, default=Status.AKTYWNA, db_index=True, max_length=15)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    @property
    def has_active_reservations(self) -> bool:
        return self.reservations.filter(status=Reservation.Status.POTWIERDZONA).exists()

    @property
    def active_reservation_count(self) -> int:
        return self.reservations.filter(status=Reservation.Status.POTWIERDZONA).count()
```

**Walidator project_number:** zmieniony z M1 v2 (9 cyfr) na format `BUD-YYYY-NNN` zgodny z demo data z M1 (`BUD-2026-001`). Albo:
- Opcja A: pełne `BUD-YYYY-NNN` pattern (demo data matches).
- Opcja B: 9 cyfr (M1 v2 oryginalna specyfikacja).

**Rekomendacja:** Opcja A (dopasowana do demo data, `RegexValidator(r"^BUD-\d{4}-\d{3}$")`).

---

### S3-T03 — Model `Reservation`

```python
class Reservation(models.Model):
    class Status(models.TextChoices):
        OCZEKUJACA = "oczekujaca", "Oczekująca"
        POTWIERDZONA = "potwierdzona", "Potwierdzona"
        ANULOWANA = "anulowana", "Anulowana"
        ZAKONCZONA = "zakonczona", "Zakończona"

    uid = models.CharField("Nr rezerwacji", max_length=20, unique=True, db_index=True,
                            help_text="Np. RES-0001, auto-generowany")
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="reservations")
    site = models.ForeignKey(ConstructionSite, on_delete=models.PROTECT, null=True, blank=True,
                              related_name="reservations")
    start_date = models.DateField("Data od", db_index=True)
    end_date = models.DateField("Data do", db_index=True)
    person = models.CharField("Osoba odpowiedzialna", max_length=150)
    project_number = models.CharField("Numer projektu", max_length=30, blank=True, default="")
    address = models.CharField("Adres budowy", max_length=300, blank=True, default="")
    status = models.CharField(choices=Status.choices, default=Status.OCZEKUJACA, db_index=True, max_length=15)
    notes = models.TextField("Notatki", blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-start_date"]
        indexes = [models.Index(fields=["machine", "status", "start_date"], name="idx_res_m_s_sd")]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")),
                                    name="reservation_end_gte_start"),
        ]

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Data końca nie może być wcześniejsza niż data początku."})
        if self.machine_id and self.start_date and self.end_date:
            overlapping = Reservation.objects.filter(
                machine_id=self.machine_id,
                status=self.Status.POTWIERDZONA,
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            ).exclude(pk=self.pk)
            if overlapping.exists():
                raise ValidationError("Rezerwacja koliduje z inną potwierdzoną rezerwacją tej maszyny.")

    @property
    def title(self) -> str:
        return f"{self.project_number or '—'} / {self.person}"

    def save(self, *args, **kwargs):
        if not self.uid:
            self.uid = self._generate_uid()
        super().save(*args, **kwargs)

    @classmethod
    def _generate_uid(cls) -> str:
        last = cls.objects.order_by("-uid").values_list("uid", flat=True).first()
        if last:
            try:
                n = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                n = 1
        else:
            n = 1
        return f"RES-{n:04d}"
```

---

### S3-T04 — Service `has_conflict` + `run_daily_sync` (port z M1 na ORM)

```python
# reservations/services.py
def has_conflict(machine, start_date, end_date, exclude_pk=None) -> bool:
    qs = Reservation.objects.filter(
        machine=machine,
        status__in=(Reservation.Status.OCZEKUJACA, Reservation.Status.POTWIERDZONA),
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()

@transaction.atomic
def run_daily_sync(today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    updated = extended = reserved = 0

    # Przebieg 1: aktywne / przeterminowane / przyszłe
    confirmed = Reservation.objects.filter(
        status=Reservation.Status.POTWIERDZONA,
        end_date__gte=today - timedelta(days=30),
    ).select_related("machine")

    for res in confirmed:
        m = res.machine
        if m.status == Machine.Status.W_SERWISIE:
            continue
        if res.start_date <= today <= res.end_date:
            if m.status != Machine.Status.NA_BUDOWIE:
                m.status = Machine.Status.NA_BUDOWIE
                m.location = res.address or m.location
                m.save(update_fields=["status", "location", "updated_at"])
                updated += 1
        elif res.end_date < today:
            if m.status == Machine.Status.NA_BUDOWIE:
                res.end_date = today
                res.save(update_fields=["end_date", "updated_at"])
                extended += 1
            elif m.status == Machine.Status.ZAREZEROWOWANA:
                m.status = Machine.Status.W_MAGAZYNIE
                m.location = Machine.DEFAULT_LOCATION
                m.save(update_fields=["status", "location", "updated_at"])
                updated += 1
        elif res.start_date > today and m.status == Machine.Status.W_MAGAZYNIE:
            m.status = Machine.Status.ZAREZEROWOWANA
            m.save(update_fields=["status", "updated_at"])
            reserved += 1

    # Przebieg 2: order-independence fix (z M1)
    ...

    return {"updated": updated, "extended": extended, "reserved": reserved}
```

---

### S3-T05 — Service `create_reservation` + `cancel_reservation` + `complete_reservation`

Port z M1 `ui.py` funkcji, ale jako pure service functions z `@transaction.atomic`.

---

### S3-T06 — View: reservation_list + partials

- Filtry: status, machine, site, date range.
- Grupowanie po statusie (accordion w Alpine — 4 sekcje: Oczekujące / Potwierdzone / Zakończone / Anulowane).
- HTMX `hx-get` dla filter apply bez reload.

---

### S3-T07 — View: reservation_create + reservation_modal_create (HTMX modal)

- Standalone page `/reservations/create/`.
- **+** modal variant `/reservations/modal/create/?machine_id=X` — HTMX fragment, używany z timeline (kliknięcie "+Rezerwacja" na konkretnej maszynie).
- Na POST success: `HX-Trigger: {"closeModal": true, "refreshTimeline": true, "showToast": {"message": "...", "level": "success"}}`.

---

### S3-T08 — View: reservation_edit + reservation_modal (HTMX modal)

- Edit via modal lub standalone page.
- Conflict check w `clean()` przez `exclude_pk=self.pk`.
- Datepicker Flatpickr z polską lokalizacją.

---

### S3-T09 — View: reservation_cancel + reservation_complete

- POST only z `@require_http_methods(["POST"])`.
- Po cancel: maszyna reset status jeśli brak innych aktywnych.
- Po complete: wywołaj `machines.services.return_machine(machine, today)`.

---

### S3-T10 — View: construction_site CRUD (list + create + edit + delete)

- `/sites/` — lista z filtrami status + search.
- `/sites/<pk>/` — detail z rezerwacjami tej budowy.
- `/sites/create/` + `/sites/<pk>/edit/`.
- `/sites/<pk>/delete/` — **POST only** + `has_active_reservations` check.

---

### S3-T11 — View: `site_create_inline` (HTMX partial z formularza rezerwacji)

- Mały formularz otwierany w modalu z `reservation_create`.
- GET → fragment HTML. POST → tworzy site + zwraca success fragment z `HX-Trigger: refreshSites`.

---

### S3-T12 — Tests: conflict detection (pytest + hypothesis)

```python
from hypothesis import given, strategies as st
from datetime import date, timedelta

@given(
    start_offset=st.integers(min_value=-365, max_value=365),
    duration_days=st.integers(min_value=0, max_value=365),
)
def test_has_conflict_symmetric(start_offset, duration_days):
    """Własność: konflikt A↔B jest symetryczny."""
    ...

@given(...)
def test_has_conflict_disjoint_ranges_no_conflict():
    """Rozłączne zakresy — brak konfliktu."""
    ...
```

---

### S3-T13 — Tests: daily sync (pytest + freezegun)

```python
from freezegun import freeze_time

@freeze_time("2026-05-15")
def test_overdue_extends_end_date():
    """Przeterminowana rezerwacja (Na budowie) → end_date = 2026-05-15."""
    m = OnSiteMachineFactory()
    r = ReservationFactory(machine=m, start_date="2026-05-01", end_date="2026-05-10",
                            status=Reservation.Status.POTWIERDZONA)
    result = run_daily_sync()
    r.refresh_from_db()
    assert r.end_date == date(2026, 5, 15)
    assert result["extended"] == 1
```

---

### S3-T14 — Seed reservations z M1 JSON

Extension `seed_all` o `--reservations` option. Import z `archive/milestone-1/console/data/reservations.json` → Reservation objects. Wymaga mapowania:
- `"oczekująca"` → `Reservation.Status.OCZEKUJACA` (snake case fix)
- `"potwierdzona"` → `Reservation.Status.POTWIERDZONA`
- etc.

Tworzy ConstructionSite dla każdego unikalnego `projectNumber` + `address`.

---

### S3-T15 — Dashboard stats (częściowo) — reservations count + pending

Dodaj do `machines.views.dashboard`:

```python
pending_count = Reservation.objects.filter(status=Reservation.Status.OCZEKUJACA).count()
overdue_count = Reservation.objects.filter(
    status=Reservation.Status.POTWIERDZONA,
    end_date__lt=today,
    machine__status=Machine.Status.NA_BUDOWIE,
).count()
```

Dashboard card: "Oczekują na zatwierdzenie: X" + "Zwroty spóźnione: Y".

## DoD Sprint 3

- [ ] App `reservations` z 2 modelami: Reservation + ConstructionSite.
- [ ] Migracje + data migration (seed z M1 JSON).
- [ ] Admin z inline ProjectNumber? (jeśli mamy ten model — w tym M2 nie, to było rozszerzenie poza zakresem projektu).
- [ ] 15+ widoków (list, detail, create, edit, cancel, complete dla reservations; list, detail, create, edit, delete, inline-create dla sites).
- [ ] Services: `has_conflict`, `run_daily_sync`, `create_reservation`, `update_reservation`, `cancel_reservation`, `complete_reservation`, `create_site`, `update_site`, `delete_site`.
- [ ] 40+ testów (unit + integration), z hypothesis i freezegun.
- [ ] Dashboard pokazuje pending + overdue counters.
- [ ] Merge → develop.

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ 🔧 SPRINT 4 (11.05 – 17.05) ─── Serwis + Decimal + dateutil 🔧    ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** App `service` z modelem `ServiceRecord` (z **DecimalField** cost — naprawa tech debt z M1), auto-update machine.inspection_date, widok historii z filtrami i kosztami, bulk inspection, CSV export.

**Branch:** `feature/m2-s4-service`

## Taski

### S4-T01 — App `service`

---

### S4-T02 — Model `ServiceRecord` (DecimalField + relativedelta)

```python
from decimal import Decimal
from dateutil.relativedelta import relativedelta

class ServiceRecord(models.Model):
    class RecordType(models.TextChoices):
        PRZEGLAD_KWARTALNY = "przeglad_kwartalny", "Przegląd kwartalny (3 mc)"
        PRZEGLAD_ROCZNY = "przeglad_roczny", "Przegląd roczny (12 mc)"
        NAPRAWA = "naprawa", "Naprawa"

    INSPECTION_INTERVALS = {
        "przeglad_kwartalny": 3,
        "przeglad_roczny": 12,
    }

    uid = models.CharField("Nr wpisu", max_length=20, unique=True, db_index=True)
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="service_records")
    performed_date = models.DateField("Data wykonania", db_index=True)
    record_type = models.CharField(choices=RecordType.choices, max_length=20, db_index=True)
    description = models.TextField("Opis", blank=True, default="")
    cost = models.DecimalField(
        "Koszt (PLN)", max_digits=10, decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    next_inspection = models.DateField("Następny przegląd", null=True, blank=True)
    inspection_document = models.FileField(
        "Dokument (PDF)", upload_to="inspections/", blank=True, null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["-performed_date"]

    @staticmethod
    def calculate_next_inspection(performed_date: date, interval_months: int) -> date:
        """Poprawna kalendarzowa arytmetyka (M1 miała 30 dni/miesiąc — bug)."""
        return performed_date + relativedelta(months=interval_months)

    def save(self, *args, **kwargs):
        if not self.uid:
            self.uid = self._generate_uid()
        # Auto-calc next_inspection for inspections
        if self.record_type in self.INSPECTION_INTERVALS:
            interval = self.INSPECTION_INTERVALS[self.record_type]
            self.next_inspection = self.calculate_next_inspection(self.performed_date, interval)
        super().save(*args, **kwargs)
        # Auto-update machine.inspection_date
        if self.record_type in self.INSPECTION_INTERVALS and self.machine_id:
            self.machine.inspection_date = self.next_inspection
            self.machine.save(update_fields=["inspection_date", "updated_at"])
```

**Naprawa tech debt M1:**
- M1: `cost: float` → M2: `cost: Decimal` (money arithmetic).
- M1: `calculate_next_inspection`: `timedelta(days=interval * 30)` → M2: `relativedelta(months=interval)` (prawdziwe miesiące kalendarzowe).

---

### S4-T03 — Admin `ServiceRecordAdmin`

```python
class ServiceRecordAdmin(ModelAdmin, SimpleHistoryAdmin):
    list_display = ["uid", "machine_uid", "performed_date", "record_type", "cost", "next_inspection"]
    list_filter = ["record_type", "performed_date"]
    search_fields = ["machine__uid", "machine__name", "description", "uid"]
    date_hierarchy = "performed_date"
    raw_id_fields = ["machine"]
    readonly_fields = ["uid", "next_inspection", "created_at", "updated_at"]
```

---

### S4-T04 — Service `add_service_record` + `update_service_record`

---

### S4-T05 — View `service_history` z filtrami (machine, date range)

- Query params: `machine`, `from_date`, `to_date`.
- Paginator 50.
- HTMX partial `_service_table.html`.
- RBAC: `can_see_costs = user.is_staff` (tylko admin/magazynier widzi kwoty).

---

### S4-T06 — View `service_add(machine_pk)` + form

- Form per-record-type:
  - `przeglad_*` — bez cost input, z interval auto, z optional document upload.
  - `naprawa` — z cost input (walidacja: polska notacja — przecinek jako separator).
- Po zapisie: jeśli machine.status == W_SERWISIE i form ma `close_service=True` → call `machines.services.close_service(machine)`.

---

### S4-T07 — View `bulk_inspection` (mass operation)

- Checkboxy dla wszystkich maszyn (grupowane po typie).
- Wspólna data przeglądu, wspólny PDF (file shared across records).
- `transaction.atomic` dla wszystkich insertów.

---

### S4-T08 — View `service_export_csv` (streaming + UTF-8 BOM + injection protection)

```python
def _sanitize_csv(value):
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s

def service_export_csv(request):
    def _rows():
        writer = csv.writer(_Echo())
        yield "\ufeff"  # BOM for Excel
        yield writer.writerow(["Data", "Maszyna", "Typ", "Opis", "Koszt"])
        for r in records.iterator():
            yield writer.writerow([r.performed_date.isoformat(),
                                     _sanitize_csv(r.machine.uid),
                                     r.get_record_type_display(),
                                     _sanitize_csv(r.description),
                                     str(r.cost)])
    response = StreamingHttpResponse(_rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="serwis.csv"'
    return response
```

---

### S4-T09 — View `service_record_modal` (HTMX modal: edit + delete)

---

### S4-T10 — Tests: ServiceRecord model + calculate_next_inspection edge cases

```python
def test_calculate_next_inspection_3_months():
    result = ServiceRecord.calculate_next_inspection(date(2026, 1, 16), 3)
    assert result == date(2026, 4, 16)  # kalendarzowo, nie 90 dni

def test_calculate_next_inspection_leap_year():
    result = ServiceRecord.calculate_next_inspection(date(2024, 2, 29), 12)
    assert result == date(2025, 2, 28)  # relativedelta smart

def test_cost_is_decimal_not_float():
    sr = ServiceRecord(..., cost=Decimal("1234.56"))
    sr.save()
    sr.refresh_from_db()
    assert isinstance(sr.cost, Decimal)
    assert sr.cost == Decimal("1234.56")  # żadnej floating point imprecision
```

---

### S4-T11 — Tests: integration service_add + bulk_inspection + CSV export

---

### S4-T12 — Seed service records z M1 (~150 wpisów)

Extension `seed_all` o `--service` option. Import z `archive/milestone-1/console/data/service_records.json`. Mapowanie:
- `"przegląd"` z M1 → M2 **nieokreślony** (kwartalny/roczny musimy zgadnąć z interwału w danych, lub ustawić wszystkie na `przeglad_roczny`).
- `"naprawa"` → `NAPRAWA`.
- Konwertuj float cost → Decimal.

**Decyzja:** przy imporcie patrz na `interval` z oryginalnego rekordu (jeśli next_inspection - performed_date ≈ 3 mc → kwartalny, ≈ 12 mc → roczny, else kwartalny jako default).

---

### S4-T13 — Update machine_detail template: sekcja "Ostatnie wpisy serwisowe"

- Top 10 wpisów dla tej maszyny.
- Total cost agregat.
- Link "Zobacz pełną historię".

## DoD Sprint 4

- [ ] App `service` z modelem + admin + services + views + forms.
- [ ] Naprawa tech debt M1: `Decimal` cost + `relativedelta` calc.
- [ ] `seed_all --service` działa.
- [ ] CSV export streaming z BOM + injection protection.
- [ ] Bulk inspection mass operation.
- [ ] 30+ testów (+coverage 80%).
- [ ] Merge → develop.

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ 🎨 SPRINT 5 (18.05 – 24.05) ─── Timeline skeleton + filtry 🎨     ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** **Timeline** (CSS Grid, HTMX partial) — to **flagowy widok** aplikacji. Sticky controls, nawigacja tydzień/miesiąc, filtry Alpine popover, pending banner, overdue alert. Alpine reactive state zostawiamy na S6 — S5 to wersja HTMX-first.

**Branch:** `feature/m2-s5-timeline-skeleton`

## Taski

### S5-T01 — Helper `_build_timeline_context(start_date, days_count, filters)`

- Input: start_date, days_count (7/14/30), machine_type (CSV), statuses_filter (CSV).
- Output dict: machine_rows (list), day_list, nav dates (prev/next week/month), period_label, types, statuses, today.
- Ograniczenie queryset-u do rezerwacji w zakresie dat (performance).
- Grupowanie rezerwacji per maszyna.
- Kalkulacja `left_pct` + `width_pct` dla każdego paska.

---

### S5-T02 — View `machines.views.timeline` (HTMX partial only)

- Non-HTMX → redirect do `/machines/dashboard/` (avoid broken direct-browser).
- HTMX request → render partial `_timeline_grid.html`.

---

### S5-T03 — View `machines.views.dashboard` (full page + embeds timeline)

- Quick stats cards (4): total / W magazynie / Na budowie / W serwisie.
- Overdue alert (session flag "shown once per day").
- Pending reservations banner (admin only).
- Timeline embed.
- Recent reservations table (5 ostatnich).

---

### S5-T04 — Template `dashboard.html` — structure + Tailwind styling

- Grid: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`.
- Cards z `bg-white rounded-xl shadow-sm border border-gray-200 p-5`.
- Status badges z odpowiednimi kolorami (bg-green-100 text-green-700 dla "W magazynie" etc.).

---

### S5-T05 — Template `_timeline_grid.html` (CSS Grid)

Strukturę przepisujemy ze sprawdzonego wzorca `machines/_timeline_grid.html`:

- Sticky header row z days (`sticky top: var(--tl-ctrl-h, 0px);`).
- Weekend days highlighted (`bg-gray-100`), today (`bg-blue-50`).
- Machine rows z inspection coloring (bg-red-50 overdue, bg-yellow-50 warning).
- Machine sidebar (32x32 image + UID link + name truncate + status badge).
- Bars positioned `left: {{ bar.left_pct }}%; width: calc({{ bar.width_pct }}% - 2px)`.
- Bar coloring macierz **status × inspection_status**:
  - `potwierdzona + overdue`: bg `#dc2626` + border `#991b1b`
  - `potwierdzona + warning`: bg `#f59e0b` + border `#d97706`
  - `potwierdzona + ok`: bg `#0f766e` (teal brand) + border `#0d6963`
  - `oczekująca` (dashed borders, bg 20% opacity) + per inspection:
    - overdue: bg `rgba(220,38,38,0.2)` + dashed border red
    - warning: bg `rgba(245,158,11,0.2)` + dashed border amber
    - ok: bg `rgba(15,118,110,0.2)` + dashed border teal

---

### S5-T06 — Sticky Controls row z JS CSS variable

```html
<div id="tl-controls" class="sticky top-0 z-30 -mx-6 px-6 pt-3 pb-3 border-b bg-gray-100">
  <!-- controls -->
</div>

<script>
(function() {
  var ctrl = document.getElementById('tl-controls');
  if (ctrl) {
    function setH() { document.documentElement.style.setProperty('--tl-ctrl-h', ctrl.offsetHeight + 'px'); }
    setH();
    window.addEventListener('resize', setH);
  }
})();
</script>
```

Header row timeline grid używa `top: var(--tl-ctrl-h, 0px);` dla poprawnego offsetu pod sticky controls.

---

### S5-T07 — Week + Month navigation buttons (query params)

```html
<a href="?view={{ view_type }}&start={{ prev_week }}" title="-7 dni">←</a>
<a href="?view={{ view_type }}&start={{ next_week }}" title="+7 dni">→</a>
<a href="?view={{ view_type }}&start={{ prev_month }}" title="-30 dni">«</a>
<a href="?view={{ view_type }}&start={{ next_month }}" title="+30 dni">»</a>
```

Non-HTMX (full page reload). W S6 zmienimy na HTMX + Alpine state.

---

### S5-T08 — View type toggle (7d / 2tyg / M)

---

### S5-T09 — Period label w języku polskim

`MONTHS_PL` w `planer/constants.py`:

```python
MONTHS_PL = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia",
}
```

Format: `7 kwietnia – 20 kwietnia 2026` (same month), `28 kwietnia – 4 maja 2026` (cross month), `20 grudnia 2026 – 3 stycznia 2027` (cross year).

---

### S5-T10 — Filter popover (Alpine x-data, types + statuses checkboxes)

```html
<div x-data="{
  open: false,
  types: { {% for val, label in types %}'{{ val }}': {% if val in selected_types %}true{% else %}false{% endif %}{% if not forloop.last %}, {% endif %}{% endfor %} },
  statuses: {...},
  get activeCount() { ... },
  applyFilters() { window.location.search = new URLSearchParams({...}).toString(); },
  clearFilters() { window.location.search = 'view={{ view_type }}&start={{ start }}'; }
}">
  <button @click="open = !open">Filtry <span x-show="activeCount > 0" x-text="activeCount"></span></button>
  <div x-show="open" @click.outside="open = false" @keydown.escape.window="open = false" x-transition>
    <!-- checkboxes -->
    <button @click="applyFilters()">Zastosuj</button>
    <button @click="clearFilters()">Wyczyść</button>
  </div>
</div>
```

---

### S5-T11 — Tooltip per reservation bar (Alpine, keyboard a11y)

```html
<div x-data="{ showTip: false }"
     @mouseenter="showTip = true" @mouseleave="showTip = false"
     @focus="showTip = true" @blur="showTip = false"
     tabindex="0">
  <a href="{% url 'reservations:detail' res.pk %}" class="bar...">
    <span class="truncate">{{ bar.label }}</span>
  </a>
  <div x-show="showTip" x-transition class="tooltip-content">
    <!-- res.title, dates, person, site, status -->
  </div>
</div>
```

---

### S5-T12 — Pending reservations banner (admin only)

```html
{% if pending_count and is_admin_or_magazynier %}
  <div class="rounded-lg p-4 bg-amber-50 border border-amber-200">
    <span class="font-medium text-amber-900">
      {% if pending_count == 1 %}1 rezerwacja czeka na zatwierdzenie
      {% elif pending_count >= 2 and pending_count <= 4 %}{{ pending_count }} rezerwacje czekają na zatwierdzenie
      {% else %}{{ pending_count }} rezerwacji czeka na zatwierdzenie
      {% endif %}
    </span>
    <a href="{% url 'reservations:list' %}?status=oczekujaca" class="underline">Zatwierdź →</a>
  </div>
{% endif %}
```

---

### S5-T13 — Overdue alert (session-tracked, "shown once per day")

```python
today = date.today()
session_key = f"sync_shown_{today.isoformat()}"
show_sync = False
overdue_count = 0
if not request.session.get(session_key):
    overdue_count = Reservation.objects.filter(
        end_date__lt=today,
        status=Reservation.Status.POTWIERDZONA,
        machine__status=Machine.Status.NA_BUDOWIE,
    ).count()
    if overdue_count > 0:
        show_sync = True
        request.session[session_key] = True
```

Banner: "Na budowie X maszyn z przeterminowaną rezerwacją. Uruchom sync →".

---

### S5-T14 — "Dziś" button (jump to current week)

```html
<a href="?view={{ view_type }}" class="...">Dziś</a>
```

---

### S5-T15 — Tests: timeline context helper + view

- `test_timeline_context_shape` — assert klucze dict + types.
- `test_timeline_filter_by_type` — tylko maszyny danego typu.
- `test_timeline_filter_by_status` — tylko ten status.
- `test_timeline_htmx_partial_response` — HX-Request → partial.
- `test_timeline_non_htmx_redirects_to_dashboard`.

## DoD Sprint 5

- [ ] Dashboard z 4 KPI + pending + overdue + timeline embed + recent reservations.
- [ ] Timeline CSS Grid z sticky controls.
- [ ] Filtry Alpine popover działają (page reload).
- [ ] Nawigacja week/month/today działa.
- [ ] Period label po polsku (pełne nazwy miesięcy).
- [ ] Bar coloring matrix status × inspection.
- [ ] Tooltip z keyboard a11y.
- [ ] Pending + overdue banery.
- [ ] 20+ testów integracyjnych timeline.
- [ ] Merge → develop.

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ ⚡ SPRINT 6 (25.05 – 31.05) ─── Alpine Reactive Refactor ⚡       ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** Timeline + modal edit przepisane na **Alpine Reactive Derived UI State** pattern. Kliknięcia = instant UI response (bez server round-trip). Edit w modalu modyfikuje Alpine state → `current*` getters przeliczają UI w 10 miejscach → explicit commit → server save.

**Branch:** `feature/m2-s6-alpine-reactive`

## Taski

### S6-T01 — Backend: json_script hydration context

`machines.views.dashboard` + `timeline` rozszerzenie context:

```python
context = {
    "machines_data": list(Machine.objects.values("pk", "uid", "name", "status", "machine_type", "inspection_date")),
    "reservations_data": list(Reservation.objects.filter(...).values("pk", "machine_id", "start_date", "end_date", "status", "person", ...)),
    "status_colors": {
        "potwierdzona": {"bg": "#0f766e", "border": "#0d6963", "text": "white"},
        "oczekujaca": {"bg": "rgba(15,118,110,0.2)", "border": "#0f766e", "text": "#0f766e"},
    },
    "inspection_status_colors": {...},
    "view_config": {"start": start.isoformat(), "days_count": days_count, "view_type": view_type},
}
```

Template:

```html
{{ machines_data|json_script:"machines-data" }}
{{ reservations_data|json_script:"reservations-data" }}
{{ status_colors|json_script:"status-colors" }}
{{ view_config|json_script:"view-config" }}
```

---

### S6-T02 — `timelineShell()` Alpine component

```javascript
function timelineShell() {
  return {
    // State z json_script
    machines: [],
    reservations: [],
    statusColors: {},
    viewConfig: {},
    // Edit state (Alpine-only draft)
    editModal: { open: false, reservation: null, fields: {} },
    editedReservations: {},  // key: res.pk -> modified fields
    // Filter state
    selectedTypes: {},
    selectedStatuses: {},
    filterOpen: false,

    init() {
      try {
        this.machines = JSON.parse(document.getElementById('machines-data').textContent);
        this.reservations = JSON.parse(document.getElementById('reservations-data').textContent);
        this.statusColors = JSON.parse(document.getElementById('status-colors').textContent);
        this.viewConfig = JSON.parse(document.getElementById('view-config').textContent);
      } catch (e) { /* graceful fallback */ }
    },

    // Computed getters — `current*` prefix
    get currentFilteredMachines() {
      let filtered = this.machines;
      const activeTypes = Object.entries(this.selectedTypes).filter(([k,v]) => v).map(([k]) => k);
      if (activeTypes.length > 0 && activeTypes.length < Object.keys(this.selectedTypes).length) {
        filtered = filtered.filter(m => activeTypes.includes(m.machine_type));
      }
      return filtered;
    },

    currentReservationsForMachine(machineId) {
      const base = this.reservations.filter(r => r.machine_id === machineId);
      // overlay z editedReservations
      return base.map(r => {
        const edits = this.editedReservations[r.pk];
        return edits ? { ...r, ...edits, edited: true } : r;
      });
    },

    currentOccupancyForMachine(machineId) {
      const resList = this.currentReservationsForMachine(machineId);
      // ... kalkulacja procentu zajętości w bieżącym widoku
    },

    currentPendingCount() {
      return this.reservations.filter(r => r.status === 'oczekujaca').length;
    },

    // Methods
    openEdit(reservationPk) {
      const res = this.reservations.find(r => r.pk === reservationPk);
      this.editModal.reservation = res;
      this.editModal.fields = this.editedReservations[reservationPk] || { ...res };
      this.editModal.open = true;
    },

    saveEdit() {
      // Zapis DO Alpine state (NIE do DB yet)
      this.editedReservations[this.editModal.reservation.pk] = { ...this.editModal.fields };
      this.editModal.open = false;
    },

    discardEdits() {
      this.editedReservations = {};
    },

    // Private helpers — `_*` prefix
    _colorForReservation(res) {
      return this.statusColors[res.status] || this.statusColors.default;
    },

    _barLeftPct(res) {
      // calc based on viewConfig.start + days_count
      ...
    },

    _barWidthPct(res) {
      ...
    },
  };
}
```

---

### S6-T03 — Template `_timeline_grid.html` przepisanie na `<template x-for>`

```html
<div x-data="timelineShell()" x-init="init()">

  <!-- Header row: dni -->
  <template x-for="day in _dayList" :key="day.iso">
    <div :class="day.isToday ? 'bg-blue-50 font-bold' : (day.isWeekend ? 'bg-gray-100' : '')">
      ...
    </div>
  </template>

  <!-- Machine rows -->
  <template x-for="machine in currentFilteredMachines" :key="machine.pk">
    <div class="flex border-b...">
      <!-- sidebar -->
      <div class="w-40"><!-- ... --></div>
      <!-- bars -->
      <div class="flex-1 relative">
        <template x-for="res in currentReservationsForMachine(machine.pk)" :key="res.pk">
          <div
            :style="'left: ' + _barLeftPct(res) + '%; width: calc(' + _barWidthPct(res) + '% - 2px);'"
            :class="res.edited ? 'ring-2 ring-amber-400' : ''"
            @click="openEdit(res.pk)"
            tabindex="0"
          >
            <span x-text="res.person"></span>
            <template x-if="res.edited">
              <span class="badge">edytowana</span>
            </template>
          </div>
        </template>
      </div>
    </div>
  </template>

</div>

<!-- Edit modal -->
<div x-show="editModal.open" x-cloak ...>
  <form @submit.prevent="saveEdit()">
    <input x-model="editModal.fields.end_date" type="date" />
    <!-- ... pozostałe pola -->
    <button type="submit">Zapisz edycję (lokalnie)</button>
    <button type="button" @click="editModal.open = false">Anuluj</button>
  </form>
</div>

<!-- Commit panel (jeśli są edits) -->
<div x-show="Object.keys(editedReservations).length > 0" x-cloak>
  <span x-text="Object.keys(editedReservations).length"></span> edytowane rezerwacje — 
  <form method="post" action="{% url 'reservations:bulk_commit' %}">
    <input type="hidden" name="edited_json" :value="JSON.stringify(editedReservations)">
    <button type="submit">Zatwierdź wszystko</button>
  </form>
  <button @click="discardEdits()">Odrzuć zmiany</button>
</div>
```

---

### S6-T04 — Backend: `reservation_bulk_commit` view (validate + apply)

```python
@require_POST
@permission_required("reservations.change_reservation", raise_exception=True)
def reservation_bulk_commit(request):
    edited = json.loads(request.POST.get("edited_json", "{}"))
    errors = []
    applied = 0
    with transaction.atomic():
        for pk_str, fields in edited.items():
            try:
                pk = int(pk_str)
                res = Reservation.objects.select_for_update().get(pk=pk)
                # Validate
                if "end_date" in fields:
                    new_end = date.fromisoformat(fields["end_date"])
                    if has_conflict(res.machine, res.start_date, new_end, exclude_pk=pk):
                        errors.append(f"RES-{pk}: konflikt dat")
                        continue
                    res.end_date = new_end
                # ... apply other fields
                res.full_clean()
                res.save()
                applied += 1
            except (ValueError, ValidationError) as e:
                errors.append(f"RES-{pk_str}: {e}")
    if errors:
        messages.error(request, f"Błędy: {'; '.join(errors)}")
    messages.success(request, f"Zatwierdzono {applied} zmian.")
    return redirect("machines:dashboard")
```

---

### S6-T05 — `x-cloak` na wszystkich wrapperach (FOUC prevention)

- Każdy `x-show` / `x-if` block.
- Main `x-data="timelineShell()"` wrapper.

---

### S6-T06 — Filter popover — update do Alpine state (nie URL params)

Filter `applyFilters()` nie robi `window.location.search = ...`, tylko update `selectedTypes/selectedStatuses`. `currentFilteredMachines` reaguje automatycznie.

---

### S6-T07 — Nawigacja dates — HTMX partial + Alpine update

Prev/next/today buttons → HTMX GET `/machines/timeline/?start=...` → partial refresh → Alpine re-init z new data.

---

### S6-T08 — Tests: context vars shape (`TestTimelineViewAlpineDataM2`)

```python
class TestTimelineViewAlpineDataM2(TestCase):
    def test_machines_data_in_context(self):
        response = self.client.get("/machines/dashboard/")
        self.assertContains(response, 'id="machines-data"')
        # parsuj JSON z responsu
    def test_reservations_data_shape(self):
        # ...
    def test_status_colors_in_context(self):
        # ...
    def test_empty_get_has_empty_arrays(self):
        # graceful fallback
```

---

### S6-T09 — Tests: Alpine helpers (browser JS eval)

- Manualna weryfikacja w przeglądarce (DevTools Console):
  1. Start server, open `/machines/dashboard/`.
  2. Eval: `document.querySelector('[x-data]').__x.$data.currentPendingCount()` → porównaj z liczbą z backendu.
  3. Eval: click bar → `editModal.open === true`.
  4. Eval: zmień `editModal.fields.end_date`, wywołaj saveEdit → `editedReservations[pk]` populated.
  5. Screenshot: panel commit visible z counter.

---

### S6-T10 — Backend helper `_validate_reservation_fields(reservation, fields)`

Reusable validator dla bulk_commit + pojedynczego edit view.

---

### S6-T11 — Invalidate snapshots po commicie (spójność)

Jeśli w przyszłości dodamy "draft snapshots" (analog do snapshotów wersji roboczych), unieważnić po commit.

## DoD Sprint 6

- [ ] `timelineShell()` Alpine z `current*` getters + `_*` helpers.
- [ ] `json_script` hydration dla wszystkich dynamic data.
- [ ] Edit w modalu = Alpine-only state (zero server round-trip).
- [ ] Badge "edytowana" na zmodyfikowanych rezerwacjach.
- [ ] `x-cloak` wszędzie.
- [ ] Commit panel z counter edited + "Zatwierdź wszystko" / "Odrzuć zmiany".
- [ ] Backend `reservation_bulk_commit` validates + applies.
- [ ] `transaction.atomic() + select_for_update()`.
- [ ] 15+ testów (context shape) + DevTools eval verify.
- [ ] Merge → develop.

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ ✨ SPRINT 7 (01.06 – 07.06) ─── Dashboard polish + bulk import ✨ ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** Admin dashboard z "Lamborgini" polishem — KPI cards z sparklines, bulk CSV/Excel import maszyn, dark mode, Heroicons, glass-morphism, toasty, keyboard shortcuts. Po S7 aplikacja jest w pełni funkcjonalna i ładna.

**Branch:** `feature/m2-s7-ui-polish`

## Taski

### S7-T01 — Admin Dashboard custom landing

`/admin/` landing zastąpić własnym widokiem z KPI:

- Maszyny: total / dostępne / na budowie / w serwisie / wycofane.
- Rezerwacje: pending / active / completed this month / overdue.
- Serwis: total koszty ostatnie 30 dni / 90 dni / 12 mc.
- Chart: "Wykorzystanie maszyn" — CSS horizontal bars (szerokość = `occupied_days / total_days × 100%`).
- Top 5 maszyn najczęściej rezerwowanych.
- Top 5 budów z największym wolumenem.

---

### S7-T02 — Sparklines CSS-based (zamiast Chart.js)

```html
<div class="flex items-end gap-0.5 h-8">
  {% for value in weekly_counts %}
    <div class="w-2 bg-primary rounded-t" style="height: {{ value|percent_of_max:weekly_counts }}%;"></div>
  {% endfor %}
</div>
```

Template filter `percent_of_max` w `templatetags/dashboard_filters.py`.

---

### S7-T03 — Bulk CSV/Excel import maszyn (admin action)

- Page `/admin/machines/bulk-import/`.
- Upload form (Excel .xlsx — openpyxl).
- Preview table: które rekordy zostaną dodane / zaktualizowane.
- Confirm → atomic transaction import.
- Summary: imported X, updated Y, skipped Z z details.

---

### S7-T004 — Bulk Excel export z admin list view

Admin action "Export zaznaczonych do Excel" → openpyxl workbook z formatowaniem.

---

### S7-T05 — Dark mode: CSS custom properties + ThemePreference

`static/css/theme.css`:

```css
:root, .theme-light {
  --bg: #ffffff;
  --bg-secondary: #f9fafb;
  --text: #111827;
  --text-muted: #6b7280;
  --border: #e5e7eb;
  --primary: #0d9488;
}

.theme-dark {
  --bg: #0f172a;
  --bg-secondary: #1e293b;
  --text: #f8fafc;
  --text-muted: #94a3b8;
  --border: #334155;
  --primary: #14b8a6;
}

body { background: var(--bg); color: var(--text); }
```

User preference via session (anonymous) lub UserProfile model (zalogowany).

FOUC prevention script w `<head>` — już w S1-T07.

---

### S7-T06 — Theme toggle w nav (Alpine + persist plugin)

```html
<div x-data="{ theme: $persist('auto').as('theme') }" x-init="
  $watch('theme', val => {
    document.documentElement.classList.remove('theme-light', 'theme-dark');
    const effective = val === 'auto' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : val;
    document.documentElement.classList.add('theme-' + effective);
  });
">
  <button @click="theme = theme === 'dark' ? 'light' : 'dark'">
    <span x-show="theme === 'dark'">☀️ Jasny</span>
    <span x-show="theme === 'light'">🌙 Ciemny</span>
  </button>
</div>
```

---

### S7-T07 — Heroicons inline w templates

Stworzenie `templates/icons/` z copied SVG-ami (30-40 kluczowych): home, dashboard, calendar, wrench, list, plus, pencil, trash, filter, search, chevron-down/up/left/right, x, check, etc.

Użycie w templates: `{% include "icons/wrench.svg" %}` lub custom template tag.

---

### S7-T08 — Self-hosted fonts (Inter + JetBrains Mono)

Download woff2 files, umieść w `static/fonts/`. W `input.css`:

```css
@font-face { font-family: 'Inter'; src: url('/static/fonts/Inter-Variable.woff2'); ... }
@font-face { font-family: 'JetBrains Mono'; src: url('/static/fonts/JetBrainsMono-Variable.woff2'); ... }
```

Tailwind `font-sans` + `font-mono` update w config.

---

### S7-T09 — Glass-morphism na Dashboard cards (backdrop-filter)

```css
.card-glass {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.3);
}
.theme-dark .card-glass {
  background: rgba(30, 41, 59, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
```

---

### S7-T10 — Skeleton loaders dla HTMX

`htmx-ext-loading-states` + `hx-indicator` + skeleton component:

```html
<div hx-get="/machines/" hx-trigger="load" hx-indicator=".spinner">
  <div class="spinner htmx-indicator">
    <!-- skeleton pulse animation -->
  </div>
</div>
```

---

### S7-T11 — Toast notifications system

`templates/components/_toast.html`:

```html
<div x-data="{
  toasts: [],
  add(msg, level='info') {
    const id = Date.now();
    this.toasts.push({ id, msg, level });
    setTimeout(() => this.toasts = this.toasts.filter(t => t.id !== id), 5000);
  }
}" @show-toast.window="add($event.detail.message, $event.detail.level)">
  <div class="fixed bottom-4 right-4 space-y-2 z-50">
    <template x-for="t in toasts" :key="t.id">
      <div x-transition
           :class="{ 'bg-green-500': t.level === 'success', 'bg-red-500': t.level === 'error', ... }">
        <span x-text="t.msg"></span>
      </div>
    </template>
  </div>
</div>
```

Triggered przez HTMX response header `HX-Trigger: {"show-toast": {"message": "...", "level": "success"}}` z backend views.

---

### S7-T12 — Keyboard shortcuts + cheatsheet (? modal)

```javascript
document.addEventListener('keydown', (e) => {
  if (e.key === '?' && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
    e.preventDefault();
    Alpine.store('shortcuts').open = true;
  }
  if (e.key === 'n' && e.ctrlKey) { window.location = '/reservations/create/'; }
  if (e.key === 'Escape') { /* close modal */ }
});
```

Cheatsheet modal z listą skrótów.

---

### S7-T13 — Print-friendly CSS dla rezerwacji eksport

```css
@media print {
  header, nav, footer, .no-print { display: none; }
  body { background: white; color: black; }
  .reservation-card { page-break-inside: avoid; break-inside: avoid; }
}
```

PDF export: **reportlab** (nie w M2 — sprawdzony pattern, ale można dodać jako nice-to-have task w S7).

---

### S7-T14 — Empty states z Heroicons

Dla każdej listy pusta-strona ilustracja + CTA:

```html
{% if not machines %}
  <div class="text-center py-12">
    {% include "icons/archive-box-outline.svg" %}
    <h3>Brak maszyn</h3>
    <p>Zacznij od dodania pierwszej maszyny albo importuj z pliku Excel.</p>
    <a href="{% url 'machines:create' %}" class="btn-primary">+ Dodaj maszynę</a>
  </div>
{% endif %}
```

---

### S7-T15 — Tailwind rebuild + staticfiles collect

```bash
npx tailwindcss -i static/css/input.css -o static/vendor/tailwind.min.css --minify
uv run python manage.py collectstatic --noinput
```

## DoD Sprint 7

- [ ] Admin Dashboard custom landing z pełnymi KPI + sparklines.
- [ ] Bulk CSV/Excel import maszyn z preview + atomic.
- [ ] Excel export z admin list.
- [ ] Dark mode toggle z FOUC prevention + persist + auto/light/dark.
- [ ] Heroicons wszędzie (zamiast emoji).
- [ ] Inter + JetBrains Mono self-hosted.
- [ ] Glass-morphism na cards.
- [ ] Skeleton loaders HTMX.
- [ ] Toast notifications system.
- [ ] Keyboard shortcuts + ? modal.
- [ ] Print-friendly CSS.
- [ ] Empty states z illustrations.
- [ ] **Aplikacja w 100% funkcjonalna do końca S7.**
- [ ] Merge → develop.

---

# ╔═══════════════════════════════════════════════════════════════════╗
# ║ 🧪 SPRINT 8 (08.06 – 14.06) ─── TESTING WEEK 🧪                   ║
# ╚═══════════════════════════════════════════════════════════════════╝

**Cel:** **Tylko testy + bugfixy + prezentacja.** Zero nowych feature'ów. Każdy scenariusz biznesowy przetestowany manualnie i automatycznie. Mutation testing dla sprawdzenia jakości testów. Prezentacja 14.06.

**Branch:** `feature/m2-s8-testing-week` (podzielić na sub-branche per kategoria testów jeśli wolisz).

## Plan testowania — podzielone na 12 kategorii

### TEST-CAT-A — CRUD maszyn (manualne + automatyczne)

| Scenariusz | Metoda | Expected | Status |
|------------|--------|----------|--------|
| Utwórz nową maszynę z wszystkimi polami | manual UI + `test_machine_create_full` | Maszyna w DB + history entry | [ ] |
| Utwórz maszynę z pustym UID | UI + pytest | ValidationError + form errors | [ ] |
| Utwórz maszynę z UID duplikatem | UI + pytest | IntegrityError + friendly msg | [ ] |
| Utwórz maszynę z build_year < 1950 | UI + pytest | Validation error | [ ] |
| Edytuj maszynę — zmień status W magazynie → W serwisie | UI + pytest | OK + history | [ ] |
| Edytuj maszynę — upload zdjęcia | UI | File saved w media/machines/ | [ ] |
| Edytuj maszynę — zmień UID | UI | UID change allowed (unique check) | [ ] |
| Usuń maszynę bez rezerwacji | admin | Usunięta | [ ] |
| Usuń maszynę z rezerwacjami | admin | **PROTECT error — nie można** | [ ] |
| Wycofaj maszynę (status wycofana) | UI | Status zmieniony, nie można dodać rezerwacji | [ ] |

### TEST-CAT-B — CRUD rezerwacji (manualne + automatyczne)

| Scenariusz | Status |
|------------|--------|
| Utwórz rezerwację na wolną maszynę | [ ] |
| Utwórz rezerwację — konflikt dat (exact overlap) | [ ] |
| Utwórz rezerwację — konflikt dat (partial overlap) | [ ] |
| Utwórz rezerwację — stykające się daty (end==start) — **JEST konflikt** | [ ] |
| Utwórz rezerwację — daty reversed (end < start) | [ ] |
| Utwórz rezerwację — start today → status maszyny Na budowie + location | [ ] |
| Utwórz rezerwację — start w przyszłości → status maszyny Zarezerwowana | [ ] |
| Edytuj rezerwację end_date — zmiana OK | [ ] |
| Edytuj rezerwację end_date — konflikt | [ ] |
| Edytuj rezerwację — edycja sama siebie (exclude_pk) | [ ] |
| Anuluj rezerwację pojedynczą | [ ] |
| Anuluj rezerwację — maszyna wraca do W magazynie (brak innych potwierdzonych) | [ ] |
| Anuluj rezerwację — maszyna zostaje Zarezerwowana (jest inna potwierdzona przyszła) | [ ] |
| Zakończ rezerwację aktywną → maszyna wraca do W magazynie | [ ] |
| Zakończ rezerwację aktywną → maszyna ma przyszłą → status Zarezerwowana | [ ] |
| Rezerwacja oczekująca — zatwierdź (admin) | [ ] |
| Rezerwacja oczekująca — odrzuć | [ ] |

### TEST-CAT-C — Daily sync (freezegun)

| Scenariusz | Status |
|------------|--------|
| Aktywna rezerwacja + maszyna W magazynie → Na budowie + location | [ ] |
| Przyszła rezerwacja + W magazynie → Zarezerwowana | [ ] |
| Przeterminowana rezerwacja (end < today) + Na budowie → extend end_date | [ ] |
| Przeterminowana rezerwacja + Zarezerwowana (no activation) → reset W magazynie | [ ] |
| Maszyna W serwisie → sync skip | [ ] |
| Wiele rezerwacji (aktywna + przyszła) — aktywna wygrywa | [ ] |
| Order-independence (2 przebiegi) | [ ] |
| Pusta DB — sync no error | [ ] |

### TEST-CAT-D — Konstrukcje (budowy)

| Scenariusz | Status |
|------------|--------|
| Utwórz budowę z poprawnym project_number (BUD-2026-001) | [ ] |
| Utwórz budowę z niepoprawnym formatem (BUD-2026-1) | [ ] |
| Utwórz budowę — duplikat project_number | [ ] |
| Usuń budowę bez aktywnych rezerwacji | [ ] |
| Usuń budowę z aktywnymi → error | [ ] |
| Edytuj budowę — zmień status | [ ] |
| Inline create z formularza rezerwacji (HTMX) | [ ] |

### TEST-CAT-E — Service records

| Scenariusz | Status |
|------------|--------|
| Dodaj przegląd kwartalny → next_inspection = performed + 3 mc (calendar, nie 90 dni) | [ ] |
| Dodaj przegląd roczny → next_inspection = performed + 12 mc | [ ] |
| Dodaj naprawę z cost 1234.56 (Decimal) | [ ] |
| Dodaj naprawę z cost ujemnym → error | [ ] |
| Przegląd auto-update machine.inspection_date | [ ] |
| Bulk inspection 10 maszyn naraz | [ ] |
| CSV export z BOM + injection protection | [ ] |
| CSV export z filtrem (machine, date range) | [ ] |
| Usuń service record → machine.inspection_date not touched | [ ] |
| Historia serwisowa — total cost agregat | [ ] |
| RBAC: non-admin nie widzi cost column | [ ] |

### TEST-CAT-F — Timeline UI

| Scenariusz | Status |
|------------|--------|
| GET /dashboard/ — renderowanie timeline 2tyg | [ ] |
| Nawigacja tydzień wstecz/do przodu | [ ] |
| Nawigacja miesiąc wstecz/do przodu | [ ] |
| Widok 7d / 2tyg / M toggle | [ ] |
| "Dziś" button — jump do current week | [ ] |
| Filter typ maszyny (1 typ) | [ ] |
| Filter typ maszyny (multiple) | [ ] |
| Filter status maszyny | [ ] |
| Filter + nawigacja razem (preserve query params) | [ ] |
| Click pasek rezerwacji — open modal (S6) | [ ] |
| Edit w modal → Alpine state update | [ ] |
| "Zatwierdź wszystko" — bulk commit | [ ] |
| Bar coloring: potwierdzona + ok = teal solid | [ ] |
| Bar coloring: oczekująca + warning = dashed amber | [ ] |
| Bar coloring: potwierdzona + overdue = red | [ ] |
| Tooltip pokazuje się na hover + focus | [ ] |
| Sticky header row — działa przy scroll | [ ] |
| Today column highlighted | [ ] |
| Weekend columns grayed | [ ] |
| Pending banner widoczny gdy pending_count > 0 (admin) | [ ] |
| Overdue alert — shown once per day (session) | [ ] |

### TEST-CAT-G — Alpine Reactive (Sprint 6 verify)

| Scenariusz | Metoda | Status |
|------------|--------|--------|
| `json_script` obecny w response HTML | pytest `test_machines_data_in_context` | [ ] |
| `json_script` ma poprawny shape (dict keys) | pytest | [ ] |
| `timelineShell().currentPendingCount()` == backend count | DevTools eval | [ ] |
| Click bar → `editModal.open === true` | DevTools eval | [ ] |
| Change end_date → `editedReservations[pk]` populated | DevTools eval | [ ] |
| Badge "edytowana" visible na zmodyfikowanych | screenshot | [ ] |
| `x-cloak` prevention FOUC (hard reload) | manual | [ ] |
| Discard edits → `editedReservations` empty | DevTools eval | [ ] |
| Bulk commit → redirect + messages.success | pytest integration | [ ] |
| Bulk commit z konfliktem → errors widoczne | pytest | [ ] |

### TEST-CAT-H — Admin + RBAC

| Scenariusz | Status |
|------------|--------|
| Login admin + access /admin/ | [ ] |
| Login z 6 błędnych prób → axes lockout godzina | [ ] |
| Axes lockout — reset_on_success (1 poprawny wyjście ok) | [ ] |
| Admin Dashboard KPI cards load | [ ] |
| Bulk CSV/Excel import maszyn | [ ] |
| Bulk Excel export | [ ] |
| History viewer (simple-history) — widać wszystkie zmiany Machine | [ ] |
| Django admin — MachineAdmin fieldsets działa | [ ] |
| Django admin — list_editable status + location | [ ] |
| Django admin — list_filter działa | [ ] |
| Django admin — search_fields (uid, name, manufacturer) | [ ] |
| Non-admin (w grupie "montazysta") — brak dostępu do admin | [ ] |
| Non-admin (jeśli w M2) — brak dostępu do machines.delete | [ ] |

### TEST-CAT-I — Dark mode

| Scenariusz | Status |
|------------|--------|
| Toggle light → dark | [ ] |
| Toggle dark → light | [ ] |
| Toggle auto → follows system preference | [ ] |
| Persist — reload zachowuje theme | [ ] |
| FOUC prevention — hard reload bez błysku | [ ] |
| Wszystkie strony kolorystycznie spójne w dark mode | [ ] |
| Tooltips + modals dark mode | [ ] |
| Charts/sparklines widoczne w dark mode | [ ] |

### TEST-CAT-J — Security + performance

| Scenariusz | Metoda | Status |
|------------|--------|--------|
| Response ma `Content-Security-Policy` header | curl -I / pytest | [ ] |
| `X-Frame-Options: DENY` | pytest | [ ] |
| `X-Content-Type-Options: nosniff` | pytest | [ ] |
| File upload: try upload .exe → rejected | manual | [ ] |
| File upload: try 20MB file → rejected (limit 10MB) | manual | [ ] |
| XSS w reservation notes → escape'owane | manual + pytest | [ ] |
| SQL injection w search → ORM bezpieczny | pytest | [ ] |
| Timeline z 20 maszyn × 30 dni < 1s load | benchmark | [ ] |
| Admin list 1000 maszyn — pagination smooth | load test | [ ] |
| HTMX partial swap < 200ms | browser devtools | [ ] |

### TEST-CAT-K — Dane + i18n

| Scenariusz | Status |
|------------|--------|
| PostgreSQL connection działa | [ ] |
| `migrate` od zera clean | [ ] |
| `seed_all --all --clear` czyści + seeduje | [ ] |
| Backup/restore DB (pg_dump + pg_restore) | [ ] |
| Wszystkie UI strings po polsku — brak EN/NL/FR | [ ] |
| Data formatted `DD.MM.YYYY` | [ ] |
| Currency `PLN` wszędzie | [ ] |

### TEST-CAT-L — Browser compat + edge cases + performance

| Scenariusz | Status |
|------------|--------|
| Chrome desktop — all flows | [ ] |
| Firefox desktop — all flows | [ ] |
| Safari desktop — all flows | [ ] |
| Edge desktop — all flows | [ ] |
| iOS Safari (iPhone) — responsive + modals | [ ] |
| Android Chrome — responsive + modals | [ ] |
| Rezerwacja obejmująca DST change (marzec) | [ ] |
| Rezerwacja cross-year (31.12 → 1.01) | [ ] |
| Bardzo długa nazwa maszyny (truncation w UI) | [ ] |
| Unicode (ŁÓDŹ) w nazwach | [ ] |
| Special chars w notes (`<script>`) | [ ] |
| `docker compose up` fresh start | [ ] |
| Volumes persistujące DB między restarts | [ ] |
| Healthcheck `pg_isready` passes | [ ] |

### TEST-CAT-M — Mutation testing (opcjonalnie, jeśli czas)

```bash
uv run mutmut run --paths-to-mutate machines,reservations,service --tests-dir tests
uv run mutmut show
```

Analiza raportu — które linie są "survived mutations" (testy nie łapią). Dodaj brakujące testy lub oznacz jako "tested manually" w komentarzu.

---

## Plan Sprint 8 dzień-po-dniu

| Dzień | Data | Fokus |
|-------|------|-------|
| Pon | 08.06 | TEST-CAT-A + TEST-CAT-B (CRUD maszyn + rezerwacji, manualne + automatyczne) |
| Wt | 09.06 | TEST-CAT-C + TEST-CAT-D (sync freezegun + budowy) |
| Śr | 10.06 | TEST-CAT-E + TEST-CAT-F (serwis + timeline UI) |
| Czw | 11.06 | TEST-CAT-G + TEST-CAT-H (Alpine reactive + admin/RBAC) |
| Pt | 12.06 | TEST-CAT-I + TEST-CAT-J + TEST-CAT-K (dark mode + security + i18n) |
| Sob | 13.06 | TEST-CAT-L + TEST-CAT-M + BUGFIXES + README final + demo data refresh |
| Niedz | 14.06 | **PREZENTACJA** |

## DoD Sprint 8

- [ ] Wszystkie scenariusze TEST-CAT-A ... TEST-CAT-L sprawdzone.
- [ ] Mutation testing raport (optional).
- [ ] Coverage ≥ 80% (branch).
- [ ] Zero FAIL w `uv run pytest`.
- [ ] Zero naruszeń `uv run ruff check .`.
- [ ] README z final M2 stanem.
- [ ] Demo data odświeżona (seed_all --clear --all).
- [ ] Screenshoty / screencast prezentacji.
- [ ] Merge `feature/m2-s8-testing-week` → `develop` → `main` z tagiem `m2-v1.0`.

## Final merge develop → main

```bash
git switch main && git pull --ff-only
git merge --no-ff develop -m "merge: Milestone 2 — Aplikacja web Django"
git tag m2-v1.0
git push origin main --tags
```

---

# Appendix A — Git workflow cheat sheet

(Szczegółowe komendy per sprint, z sekwencją: start branch → praca → rebase → push → merge → cleanup — opisane w każdym sprincie powyżej w sekcji "Git commands".)

# Appendix B — Pre-commit hook specification

(Treść pliku `.pre-commit-config.yaml` — zobacz S1-T08.)

# Appendix C — Docker compose template

(Treść `docker-compose.yml` — zobacz S1-T04.)

# Appendix D — pyproject.toml template

(Pełna treść `pyproject.toml` — zobacz S1-T03.)

# Appendix E — Directory structure target

(Zobacz sekcja "Architektura projektu".)

# Appendix F — Definition of Done per task type

- **Task typu `model`:** model + migracja + admin + 5+ testów (creation, validation, history, queryset, edge case) + 1+ factory class.
- **Task typu `view`:** view + url + 3+ testów (GET 200, POST 302, permission required) + template rendering test.
- **Task typu `service`:** pure function + docstring + 5+ testów (happy path + edge cases + hypothesis jeśli aplikowalne).
- **Task typu `template`:** HTML + Tailwind classes + 1+ integration test że się renderuje + manualny browser check.
- **Task typu `ui-polish`:** implementacja + 1 screenshot + manualny browser check.

# Appendix G — Tech debt Milestone 1 → naprawy w Milestone 2

| M1 Tech Debt | Naprawa w M2 | Sprint |
|--------------|-------------|--------|
| `float` koszty → `DecimalField` | ServiceRecord.cost | S4-T02 |
| `30 dni/miesiąc` → `relativedelta` | ServiceRecord.calculate_next_inspection | S4-T02 |
| `VALID_STATUSES` tuples → `TextChoices` | wszystkie modele | S2-T02, S3-T02/T03, S4-T02 |
| String dates → `DateField` | wszystkie modele | S2-T02, S3-T02/T03, S4-T02 |
| `end_date >= start_date` tylko w UI → constraint DB | Reservation | S3-T03 |
| `run_daily_sync` hardcoded `date.today()` → parametr `today=None` | run_daily_sync | S3-T04 |
| JSON persistence → ORM Django | DataStore → Django Models | cała migracja |
| Console UI → Web UI | ui.py → Django views + templates | S2-S7 |
| conftest.py `sys.path` hack → pyproject.toml `pythonpath` | conftest.py | S1-T03 |
| TASK 14 (`ConstructionSite`) nigdy zaimplementowane w M1 → model w M2 | reservations | S3-T02 |
| Bug `pyproject.toml: planer = "main:main"` | Usuń sekcję lub fix | S2-T13 |
| Walidacja cost ≥ 0 tylko w UI → validator w modelu | ServiceRecord | S4-T02 |

# Appendix H — Risk register

| Ryzyko | Prawdopodobieństwo | Impact | Mitigation |
|--------|-------------------|--------|------------|
| Alpine reactive refactor (S6) bardziej skomplikowany niż zakładam | Średnia | Wysoki (kolejne sprinty opóźnione) | S6 ma 11 tasków podzielonych małymi krokami, możliwe rozdzielenie na S6+S7 jeśli trzeba. S7 polishuje + można przesunąć dark mode do M3. |
| Postgres 16 vs 18 compat — nowsza wersja problematyczna | Niska | Średni | Rekomendacja: PostgreSQL **16** (stable, dobrze supportowane). PostgreSQL 18 tylko jeśli user explicitly chce. |
| Tailwind v3 vs v4 — v4 breaking changes | Niska | Średni | Zostajemy na **v3.4.19** (Active), v4 to nowy rewrite. |
| Seed data M1 import może mieć problemy (camelCase mapping, status strings) | Średnia | Niski | Data migration + extensive testing w S2-T04. |
| CI bez PostgreSQL hostowanego → testy działają lokalnie ale nie w GitHub Actions | Niska | Niski | Services postgres w ci.yml (zobacz S1-T13). |
| S8 testing week znajdzie poważne bugi → brak czasu na fix | Wysoka | Wysoki | 7 sprintów na development + 1 tydzień bufor. Jeśli bugi krytyczne — cięcia w S7 polish (dark mode można usunąć, Heroicons zostawić emoji, etc.). |
| Prezentacja 14.06 — demo data konflikty | Średnia | Wysoki | Przed prezentacją: `seed_all --clear --all` + manual smoke test wszystkich flows. |

---

**Koniec planu Milestone 2.**

**Po przejściu M2 → M3:** zobacz `NOTES_FOR_MILESTONE_3.md` dla propozycji co rozszerzyć (i18n, RBAC, audit log, mailing, 2FA, deployment).
