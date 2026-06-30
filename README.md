# Planer Maszyn Budowlanych

[![CI](https://github.com/infoshareacademy/jpydzr10-workflow-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/infoshareacademy/jpydzr10-workflow-lab/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2%20LTS-092E20?logo=django&logoColor=white)
![Coverage](https://img.shields.io/badge/coverage-%E2%89%A580%25-success)

System rezerwacji i serwisu maszyn budowlanych dla małej firmy budowlanej.

> **Status projektu:** Milestone 3 — wersja zaawansowana aplikacji webowej Django.
> Milestone 1 (aplikacja konsolowa) został zakończony i przeniesiony do
> [`archive/milestone-1/`](archive/milestone-1/) jako materiał referencyjny.
> Milestone 2 (aplikacja web w Django) — zakończony i zaprezentowany.

## Cel Milestone 3

Rozszerzenie aplikacji webowej o funkcje produkcyjne: pełna lokalizacja
PL/EN, uwierzytelnianie dwuskładnikowe, mailing transakcyjny, raporty
(wykresy + PDF/XLSX), dostępność WCAG 2.1 AA oraz konwersacyjny asystent.

## Funkcjonalność

- Inwentarz maszyn z oznaczeniami terminów przeglądów technicznych.
- Rezerwacje maszyn z wykrywaniem konfliktów terminów + cykl statusów
  (oczekująca → potwierdzona → zakończona) z mailem potwierdzającym.
- Codzienna synchronizacja statusów (Hard Return Policy).
- Rejestr serwisowy (przeglądy + naprawy) z automatycznym obliczaniem
  terminu kolejnego przeglądu; koszty w EUR.
- Budowy (`ConstructionSite`) z numeracją projektów.
- Timeline rezerwacji w stylu Gantt — siatka maszyna × dni.
- **Raporty serwisowe:** kwartalny XLSX, roczny PDF, karta serwisowa
  maszyny (PDF) oraz wykres kosztów per maszyna (Chart.js) z eksportem
  Excel respektującym aktywne filtry.
- **Lokalizacja PL/EN** (`django.utils.translation`, katalogi `.po/.mo`)
  z przełącznikiem języka w interfejsie.
- **2FA (TOTP)** dla personelu — `django-otp` + kody zapasowe.
- **Mailing transakcyjny** (Google Workspace SMTP) — potwierdzenia rezerwacji.
- **Dostępność WCAG 2.1 AA** — kontrast, focus, cele dotykowe 44 px.
- **Asystent (chatbot)** — moduł konwersacyjny (Pydantic AI + LLM provider)
  do zapytań o maszyny i rezerwacje, z potwierdzaniem akcji zapisujących.
- Panel administracyjny w Django (motyw Tailwind przez `django-unfold`).
- Audit trail (`django-simple-history`) dla każdego modelu.
- CI (GitHub Actions): ruff, migracje, kompilacja tłumaczeń, pytest +
  coverage, bandit, pip-audit.

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
| Security | django-axes (brute-force) + django-csp (CSP + nonce) + django-otp (2FA TOTP) |
| Pieniądze | django-money (EUR) |
| Raporty | openpyxl (XLSX) + reportlab (PDF) + Chart.js (wykresy) |
| Lokalizacja | gettext (PL/EN, `.po/.mo`) |
| Asystent | Pydantic AI + LLM provider (Gemini) |
| Testy | pytest-django + factory_boy + freezegun + hypothesis + playwright |
| Linter / formatter | ruff |
| CI | GitHub Actions (ruff, pytest+coverage, bandit, pip-audit) |

Pełna lista i wersje: zobacz `pyproject.toml`.

## Uruchomienie

**Wymagania:** Python 3.14, uv, Docker (lub OrbStack na macOS).

### Szybki start (z Makefile)

```bash
make install              # uv sync (deps)
cp .env.example .env      # konfiguracja lokalna (uzupełnij brakujące pola)
make db-up                # PostgreSQL 16 na localhost:5434 (container "kursowe-repo-8002")
make migrate              # tworzy schemat bazy
make superuser            # konto admin (jednorazowo)
make run                  # Django na http://localhost:8002
```

### Bez Makefile (komendy 1:1)

```bash
uv sync
cp .env.example .env
docker compose up -d                                 # Postgres na 5434
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver 0.0.0.0:8002       # http://localhost:8002
```

### Porty (lokalne, MacOS)

| Projekt | Postgres | Django | Container Postgres w OrbStack |
|---------|----------|--------|-------------------------------|
| **Ten kursowy repo** | localhost:**5434** | http://localhost:**8002** | `kursowe-repo-8002` |
| planer-maszyn-reference (sandbox) | localhost:5433 | http://localhost:8001 | `planer-maszyn-reference-8001` |
| Inny lokalny projekt | localhost:5432 | http://localhost:8000 | (port zajęty — nie ruszać) |

Nazwa kontenera Postgres w OrbStack UI zawiera port Django — łatwo zobaczyć na jaki localhost wejść.

## Zadania cykliczne (cron)

Powiadomienia e-mail i retencja danych działają jako komendy `manage.py`
uruchamiane przez cron na produkcji:

```
# Codzienna synchronizacja statusów maszyn z rezerwacjami
0 6 * * *  cd /app && uv run python manage.py run_daily_sync
# Przypomnienia T-1 o rezerwacjach startujących jutro (idempotentne)
0 7 * * *  cd /app && uv run python manage.py send_daily_reminders
# Alerty o przeterminowanych i zbliżających się przeglądach maszyn
0 8 * * *  cd /app && uv run python manage.py send_inspection_alerts
# Retencja dziennika zdarzeń — usuwa wpisy starsze niż 90 dni (co niedzielę 3:00)
0 3 * * 0  cd /app && uv run python manage.py prune_audit_log --older-than 90
```

Wszystkie maile są dwujęzyczne (PL + EN w jednej wiadomości) i wysyłane przez
`transaction.on_commit`, więc nie wychodzą, jeśli transakcja DB się wycofa.
Nieudane wysyłki (błąd SMTP) są zapisywane w dzienniku odbić (`core.BounceLog`,
podgląd w panelu admina) i nie przerywają akcji biznesowej.

### Podgląd maili lokalnie (Mailpit)

Do testowania maili bez realnego SMTP służy **Mailpit** (łapacz maili z web UI),
uruchamiany opcjonalnym profilem `mail`:

```bash
docker compose --profile mail up -d      # Postgres + Mailpit
```

W `.env` ustaw `EMAIL_HOST=localhost`, `EMAIL_PORT=1025`, `EMAIL_USE_TLS=False`.
Przechwycone maile podejrzysz na <http://localhost:8025>. Podgląd HTML każdego
szablonu maila (PL/EN) bez wysyłki: `/admin/preview-email/` (tylko `DEBUG` + staff).
Z nieobowiązkowych powiadomień można się wypisać linkiem ze stopki maila.

## Testy

```bash
uv run pytest -q                         # wszystkie testy
uv run pytest --cov                      # z coverage (target ≥ 80%)
uv run ruff check . && uv run ruff format --check .
```

## Internacjonalizacja (PL/EN)

Interfejs jest w pełni dwujęzyczny dzięki mechanizmowi `gettext`
(`django.utils.translation`). Językiem domyślnym jest polski; tłumaczenia
angielskie żyją w katalogu `locale/en/LC_MESSAGES/django.po` (skompilowane do
`.mo`). Język wybiera się przełącznikiem w interfejsie — Django zapisuje wybór
w ciasteczku `django_language` oraz w sesji.

```python
# planer_config/settings/base.py
LANGUAGE_CODE = "pl"
LANGUAGES = [("pl", "Polski"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
```

**Dodanie nowego stringa do tłumaczenia:**

1. Oznacz tekst w kodzie/szablonie jako tłumaczalny (`_("...")`, `{% trans %}`,
   `{% blocktrans %}`).
2. `make messages` — aktualizuje `locale/en/LC_MESSAGES/django.po` o nowe
   wpisy (`makemessages -l en`).
3. Uzupełnij tłumaczenia (`msgstr`) w pliku `.po`.
4. `make compilemessages` — kompiluje `.po` → `.mo` (uruchamiane także
   automatycznie przed `make run`).

**Daty i waluta:** w całej aplikacji obowiązuje europejski format daty
`dd.mm.rrrr`. Koszty serwisowe przechowywane są jako `MoneyField`
(`django-money`) z domyślną walutą **EUR**; PLN pozostaje dostępne dla danych
historycznych z Milestone 1.

## Uwierzytelnianie dwuskładnikowe (2FA)

Konta uprzywilejowane korzystają z 2FA opartego o **TOTP** (`django-otp`),
zgodnego z aplikacjami typu Google Authenticator / Authy.

- **Pierwsze urządzenie:** `/accounts/2fa/setup/` — kod QR (`otpauth://`) do
  zeskanowania albo sekret Base32 do ręcznego wpisania, potwierdzany kodem
  jednorazowym.
- **Kody zapasowe:** po skonfigurowaniu generowanych jest **10 jednorazowych
  kodów zapasowych** (`StaticToken`) do pobrania jako plik **TXT**
  (`/accounts/2fa/recovery/download/`). Służą do logowania, gdy nie ma dostępu
  do aplikacji TOTP.
- **Wymuszenie:** flaga środowiskowa `OTP_ENFORCE_2FA` (domyślnie `1`). W dev
  można wyłączyć ustawiając `OTP_ENFORCE_2FA=0` w `.env`.
- **Role wymagające 2FA:** administrator, kierownik i magazynier muszą przejść
  drugi składnik po zalogowaniu. Montażysta (rola read-only) jest zwolniony.
  Decyzja opiera się na **funkcji** konta (`EmployeeProfile.Function`), nie na
  fladze `is_staff`.

## Mailing (SMTP)

Maile transakcyjne (potwierdzenia rezerwacji, przypomnienia, alerty przeglądów)
wysyłane są przez SMTP. Konfiguracja przez `.env` — np. Gmail / Google
Workspace z **hasłem aplikacji (App Password)**:

```dotenv
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=info@twojadomena.example
EMAIL_HOST_PASSWORD=xxxx-xxxx-xxxx-xxxx     # App Password, NIE hasło konta
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=info@twojadomena.example
```

Gdy `EMAIL_HOST` nie jest ustawiony, w dev używany jest backend konsolowy
(maile trafiają do logu), a do podglądu w przeglądarce służy Mailpit (sekcja
wyżej).

- **Dwujęzyczne treści:** każda wiadomość zawiera wersję PL i EN w jednym
  mailu.
- **Fail-soft + BounceLog:** wysyłka odbywa się przez `transaction.on_commit`,
  więc mail nie wyjdzie, jeśli transakcja DB się wycofa. Błąd SMTP nie przerywa
  akcji biznesowej — jest zapisywany w dzienniku odbić (`core.BounceLog`,
  podgląd w panelu admina).
- **Opt-out / wypisanie:** z nieobowiązkowych powiadomień można się wypisać
  linkiem ze stopki maila — strona preferencji `/accounts/preferencje-email/`
  (dostęp po podpisanym tokenie z wiadomości albo dla zalogowanego użytkownika).

## RODO / GDPR

- **Polityka prywatności:** statyczna strona `/prywatnosc/`.
- **Baner cookie:** informacja o ciasteczkach wyświetlana w stopce układu
  bazowego (`templates/base.html`).
- **Eksport danych (Art. 20):** `/accounts/moje-dane/eksport/` zwraca komplet
  danych zalogowanego użytkownika (konto, profil, rezerwacje) jako plik **JSON**
  do pobrania.
- **Prawo do bycia zapomnianym (Art. 17):** anonimizacja pracownika
  (`/accounts/pracownicy/<pk>/anonimizuj/`) usuwa dane osobowe z zachowaniem
  spójności rekordów powiązanych.
- **Retencja audytu:** wpisy dziennika zdarzeń starsze niż **90 dni** są
  usuwane przez `manage.py prune_audit_log --older-than 90` (cykliczny cron).

## Kopie zapasowe bazy

Skrypty w katalogu `scripts/` wykonują zrzut i przywrócenie bazy PostgreSQL
przez kontener `docker compose` (`pg_dump` / `psql`):

```bash
./scripts/backup_db.sh                            # zrzut → backups/planer-<db>-<timestamp>.sql.gz
BACKUP_DIR=/tmp/kopie ./scripts/backup_db.sh      # własny katalog docelowy

./scripts/restore_db.sh backups/planer-...sql.gz             # przywrócenie (pyta o potwierdzenie)
./scripts/restore_db.sh backups/...sql.gz --force            # bez pytania
./scripts/restore_db.sh backups/...sql.gz --target drill_db  # fire drill do bazy scratch
```

Przywracanie **nadpisuje** dane w bazie docelowej i domyślnie prosi o
potwierdzenie. Do prób odtworzenia (fire drill) używaj `--target` z bazą
scratch, żeby nie ruszać bazy roboczej. Na produkcji kopie warto uruchamiać
cyklicznie przez cron, np.:

```
# Codzienna kopia zapasowa bazy o 2:00
0 2 * * *  cd /app && ./scripts/backup_db.sh
```

## Architektura i dokumentacja

- [`docs/architecture.md`](docs/architecture.md) — opis architektury aplikacji.
- [`docs/erd.md`](docs/erd.md) — diagram związków encji (ERD).
- [`docs/adr/`](docs/adr/) — decyzje architektoniczne (ADR): RBAC,
  MoneyField EUR/PLN, wymuszenie 2FA, monitoring, audit log i in.
- [`docs/instrukcja-administratora.pdf`](docs/instrukcja-administratora.pdf)
  — instrukcja dla administratora.
- [`docs/instrukcja-magazyniera.pdf`](docs/instrukcja-magazyniera.pdf)
  — instrukcja dla magazyniera.

## Struktura projektu

```
planer-maszyn/
├── archive/milestone-1/      # zachowany kod M1 (console app, 175 testów)
├── planer_config/            # Django project (settings, urls, wsgi)
├── accounts/                 # app: profile pracowników, auth, 2FA
├── machines/                 # app: maszyny, statusy, przeglądy
├── reservations/             # app: rezerwacje + budowy + has_conflict
├── service/                  # app: ServiceRecord + raporty + bulk inspection
├── chatbot/                  # app: asystent konwersacyjny (+ agent głosowy)
├── core/                     # shared: utils, mixins, base templates, PDF
├── templates/                # Django templates (base.html + per-app)
├── locale/en/                # katalog tłumaczeń EN (.po/.mo)
├── static/vendor/            # HTMX, Alpine, Tailwind, Flatpickr (vendored)
├── docker-compose.yml        # PostgreSQL 16 dla dev
├── .env.example              # template konfiguracji
└── pyproject.toml            # Django + uv + ruff + pytest stack
```

## Milestone 1 (zarchiwizowane)

Aplikacja konsolowa zakończona 12.04.2026 — 175 testów PASS, 20 maszyn demo,
33 rezerwacje, 150+ wpisów serwisowych. Cały kod + testy + dane demo dostępne
w [`archive/milestone-1/`](archive/milestone-1/) jako materiał referencyjny
i baza do migracji danych.

Najważniejsze elementy biznesowe z M1 zachowane w aplikacji web:

- **Statusy maszyn:** `W magazynie`, `Na budowie`, `Zarezerwowana`, `W serwisie`.
- **Statusy rezerwacji:** `oczekująca`, `potwierdzona`, `anulowana`, `zakończona`.
- **Hard Return Policy** — przeterminowana rezerwacja przedłużana do dnia
  zwrotu zamiast automatycznego zamykania (zapobiega "gubieniu" maszyn).
- **Walidacja konfliktów** — stykające się daty traktowane jako konflikt
  (maszyna potrzebuje dnia na transport).

## Dokumenty planistyczne

- [`JIRA_TASKS_Milestone3.md`](JIRA_TASKS_Milestone3.md) — pełny plan M3 z Definition of Done.
- [`JIRA_TASKS_Milestone2.md`](JIRA_TASKS_Milestone2.md) — historyczny plan M2 (8 sprintów).
- [`NOTES_FOR_MILESTONE_3.md`](NOTES_FOR_MILESTONE_3.md) — wczesny brainstorm M3.

## Licencja

GPL-3.0-or-later — patrz [`LICENSE`](LICENSE).
