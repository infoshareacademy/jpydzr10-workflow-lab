# Notatki dla Milestone 3

> **Data utworzenia:** 2026-04-20 (podczas planowania Milestone 2).
> **Adresat:** Sebastian Nowak pracujący nad Milestone 3 (deadline 09.08.2026).
> **Status:** _Propozycje do rozważenia, nie decyzje._ Sebastian nie chciał podejmować decyzji o M3 podczas planowania M2.

---

## Kontekst

Podczas planowania Milestone 2 (aplikacja web w Django) rozważyłem wiele bibliotek, rozszerzeń i funkcjonalności, które wykraczały poza zakres M2 lub byłyby przedwczesne. Ten dokument zbiera te propozycje w jednym miejscu — jako punkt wyjścia do rozmów o M3, nie jako gotowy plan.

Milestone 3 z oryginalnego harmonogramu obejmuje:
- Logowanie zdarzeń
- Generowanie raportów o userach
- Dodatkowa wersja językowa
- Uwierzytelnianie logowania
- Mailing

Poniższe propozycje są rozszerzeniami lub alternatywami dla powyższej listy.

---

## 1. Internacjonalizacja (i18n)

Milestone 2 ma UI hardcoded po polsku. Milestone 3 powinien wprowadzić wielojęzyczność.

### Propozycja

- `django.utils.translation` + `{% trans %}` + `{% blocktrans %}` w szablonach.
- `gettext_lazy` w `models.py`, `forms.py`, `admin.py` (verbose_name, help_text, choices labels).
- Struktura `locale/<lang_code>/LC_MESSAGES/django.po`.
- Polecenia: `django-admin makemessages -l nl -l fr -l en`, `django-admin compilemessages`.
- **Języki docelowe:** polski (base), niderlandzki (firma Sebastian — belgijska), francuski (belgijska klient base), angielski (fallback). W M3 minimum PL + jeszcze jeden, reszta ambitna.
- `LANGUAGE_CODE = "pl"`, `USE_I18N = True`, `LANGUAGES = [("pl", "Polski"), ("nl", "Nederlands"), ("fr", "Français"), ("en", "English")]`.
- `LocaleMiddleware` w `MIDDLEWARE`.
- `i18n_patterns(...)` w `urls.py` — URL-e z prefiksem języka `/pl/`, `/nl/`, etc.
- **Przełącznik języka** w header — Alpine.js dropdown.

### Specjalne

- **Flatpickr** dostarcza lokalizacje gotowe: `flatpickr-pl.js`, `flatpickr-nl.js`, `flatpickr-fr.js`, etc. Zrzucić wszystkie do `static/vendor/flatpickr/l10n/`.
- **Formatowanie dat:** `USE_L10N = True` + lokalne ustawienia per język (NL/BE używa `dd-mm-yyyy` lub `dd/mm/yyyy`).
- **Format walut:** NL/BE używa `€` zamiast `zł`, plus formatowanie liczb (`1.234,56` vs `1,234.56`). Dedykowany template tag `{% currency amount %}`.

### Uwagi

- Tłumaczenie `django-unfold` — sprawdzić czy ma `.po` plik dla PL/NL/FR.
- Tłumaczenie komunikatów email (jeśli zrobione w M2) — wymaga szablonów per język.
- Admin labele — `verbose_name` + `verbose_name_plural` przez `gettext_lazy` we wszystkich modelach.

---

## 2. Uwierzytelnianie + RBAC

M1 i M2 zakładają jednego użytkownika (Sebastian = admin). M3 wprowadzi wielu użytkowników z rolami.

### Propozycja — 4 role (Django Groups)

| Rola | Django Group | Uprawnienia |
|------|-------------|-------------|
| Admin (Sebastian) | `admin` (superuser) | Pełny dostęp + konfiguracja + raporty |
| Magazynier | `magazynier` | Zarządzanie rezerwacjami, edycja stanów, planowanie |
| Kierownictwo | `kierownictwo` | Tworzenie rezerwacji, zatwierdzanie, raporty |
| Montażysta / User | `montazysta` | Wnioski o rezerwacje, read-only reszta |

### Funkcjonalności M3

- **Profil pracownika** (`accounts/EmployeeProfile`) — OneToOne z User, pola: telefon, stanowisko (TextChoices), is_active_employee, theme_preference.
- **GDPR-compliant termination:** `terminate_employee()` — ustawia flagi, data, powód. `anonymize_employee()` — pseudonimizacja PII przy zachowaniu FK w tabelach historycznych.
- **PROTECT on User delete** (nie CASCADE) — żeby historia nie ginęła.
- **Wymuszenie zmiany hasła** przy pierwszym logowaniu (`must_change_password` field).
- **Two-factor authentication** (2FA) — django-otp? django-allauth? Opcjonalnie.
- **Login rate limiting:** `django-axes` już w M2, ale w M3 podniesienie do poziomu produkcyjnego + unbanning UI dla admina.
- **RBAC w views:** `@permission_required("reservations.add_reservation", raise_exception=True)` na każdym write endpoincie.

---

## 3. Logowanie zdarzeń (audit log)

### Propozycja

- **django-simple-history** już jest w M2 dla audit trail na modelach.
- M3 doda **user activity log** — kto, kiedy, co zrobił (URL + metoda + payload).
  - Opcja A: custom middleware + model `AuditLogEntry` (user, timestamp, path, method, ip, user_agent, duration).
  - Opcja B: `django-auditlog` pakiet — gotowy, ale duplikacja z simple-history.
  - Opcja C: `django-structlog` — structured logging z contextvars, świetne do analiz.
- **UI:** admin page `/admin/audit/` z filtrowaniem po userze/dacie/akcji.
- **Eksport do CSV** z filtrami.

### Uwagi

- Wydzielić z `django-simple-history` (modelowy) i `AuditLogEntry` (user activity) — oba mają sens, pełnią różne role.
- Retention policy: 1 rok dla activity log, bezterminowo dla simple-history (history modeli nie zajmuje dużo).

---

## 4. Raporty o userach + maszynach

### Propozycja

- **Admin dashboard** w M2 już ma KPI cards. M3 rozszerza o:
  - **Wykorzystanie maszyn** (per maszyna, per miesiąc): `UsedDays/TotalDays × 100%`.
  - **Koszty serwisowe** per maszyna (top 10, trend), per rok.
  - **Ranking osób** po liczbie zrealizowanych rezerwacji.
  - **Godziny pracy pracowników** (jeśli będzie czas tracking).
- **Wykresy:**
  - M2 użyje **CSS bars** (bez biblioteki — Tailwind).
  - M3 może dodać **Chart.js** (60 KB, vendored) dla linii/kołowych. Alternatywa: **uPlot** (bardziej lekki, ale mniej features).
- **PDF eksport raportów** — ReportLab (pure Python, już pattern z M2 dla PDF rezerwacji).
- **Excel eksport** — openpyxl (już w M2 dla import/export maszyn).

---

## 5. Mailing

### Propozycja

- **Django email backend:**
  - Dev: `django.core.mail.backends.console.EmailBackend` (stdout).
  - Prod: SMTP (Gmail SMTP / Sendgrid / Postmark / AWS SES).
- **Scenariusze email:**
  - Potwierdzenie rezerwacji (do użytkownika + magazynu).
  - Anulowanie rezerwacji.
  - Odrzucenie rezerwacji (z powodem).
  - Zbliżający się termin przeglądu (14 dni przed `inspection_date` — scheduled task).
  - Przeterminowany zwrot maszyny (Hard Return Policy reminder).
  - Reset hasła.
  - Powitalny email dla nowego pracownika.
- **Szablony email:** `templates/emails/*.html` + `*.txt` plaintext fallback.
- **i18n w emailach:** `django.utils.translation.activate(user.language)` przed renderowaniem.
- **`transaction.on_commit`** pattern dla async — wysyłka po commit transakcji DB (nigdy w trakcie, bo rollback wyśle spam).
- **`fail_silently=True`** + `try/except` + `logger.exception(...)` — email nigdy nie crashuje flow biznesowego.

### Async (opcjonalnie — Celery + Redis)

- Jeśli wolumen emaili rośnie lub mailing blokuje response, wprowadzić Celery:
  - `celery` + `redis` packages.
  - `CELERY_BROKER_URL = "redis://localhost:6379/0"`.
  - Task `send_reservation_email.delay(res_id)` zamiast synchronicznej wysyłki.
  - **Celery beat schedule:** daily sync (jak w M1 `run_daily_sync`), cotygodniowy digest, reminder o przeglądach.
- **OrbStack + docker-compose** już w M2 — wystarczy dodać service `redis: image: redis:7-alpine`.

---

## 6. Biblioteki / rozszerzenia rozważane w M2, odłożone do M3

### Frontend

| Biblioteka | Rozmiar | Cel | Dlaczego odłożone |
|-----------|---------|-----|-------------------|
| **Tippy.js** | ~10 KB | Hover preview na paskach rezerwacji | M2 używa natywnego Alpine `x-data` + `@mouseenter`/`@mouseleave` + `x-show` z transition (10 linii kodu). W M3 można rozważyć Tippy dla bardziej dopracowanych animacji i placement auto-flip. |
| **SortableJS** | ~40 KB | Drag & drop rezerwacji na timeline (przeciągnij rezerwację na inny dzień / inną maszynę → POST przez HTMX na drop) | M2 ma modal edit, co wystarczy. Drag & drop = wow, ale osobny sprint. Wskazane dopiero jak user base > 10 użytkowników. |
| **Frappe Gantt** | ~40 KB | Timeline z drag-resize bar, zoom, dependencies | Custom CSS Grid + SortableJS zrobi to samo w M3 bez Gantt lib. Frappe Gantt jeśli chcemy dependencies (A musi skończyć się przed B). |
| **Chart.js** | ~60 KB | Wykresy KPI w adminie | M2 używa CSS bars Tailwind. W M3 chart.js daje interaktywność (hover tooltip, legend toggle). |
| **uPlot** | ~20 KB | Alternatywa dla Chart.js, super lekki | Jeśli potrzebujemy tylko line charts — uPlot >>> Chart.js rozmiarem. |
| **DaisyUI** | — | Tailwind component library | Konflikt z custom design. W M3 jeśli komponenty Tailwind są tworzone ad-hoc i chcemy je ustandaryzować. |
| **django-components** | — | Server-side component framework | Interesting dla DRY templatów ale niedojrzałe. W M3 można rozważyć dla partialek timeline/modal które dużo się powtarzają. |

### Backend / Django

| Pakiet | Cel | Dlaczego odłożone |
|--------|-----|-------------------|
| **django-import-export** | Bulk CSV/Excel import/export w adminie | M2 ma custom management command. Ta lib daje UI w adminie — w M3 przy rosnącej ilości maszyn/rezerwacji. |
| **django-filter** | Filterset classes dla list views | M2 robi to ręcznie w views. Django-filter daje declarative DRY — w M3 jak views komplikują się. |
| **django-ninja** | REST API z type hints + Swagger | M2 ma tylko web UI. W M3 jak chcemy udostępnić API dla mobile app / innej firmy / chatbota. |
| **django-channels** + **daphne** | WebSocket + ASGI | M2 jest synchroniczny. Channels w M3 jeśli chcemy real-time updates timeline (wiele osób ogląda ten sam widok, ktoś edytuje → reszta widzi live). |
| **django-mptt** | Drzewa hierarchiczne | M2 nie potrzebuje drzew. W M3 jeśli dodamy kategoryzację maszyn lub drzewo budów (macierzysta firma → podwykonawcy). |
| **django-select2** | Rich select widgets z AJAX search | Alpine + HTMX `lookup_site` endpoint w M2 zrobi podobne. django-select2 jeśli fancy UX. |
| **django-crispy-forms** | Bootstrap/Tailwind form rendering | `widget.attrs = {"class": "..."}` w formach M2 wystarczy. Crispy dla projektów z WIELOMA formularzami. |

### Testing

| Pakiet | Cel | Dlaczego odłożone |
|--------|-----|-------------------|
| **tox** | Multi-version testing | M2 targetuje tylko Python 3.13 (i Django 5.2). Tox gdy mamy kilka Python/Django kombinacji. |
| **pytest-benchmark** | Performance tests | M2 ma mały dataset. W M3 jeśli timeline z 200 maszyn × 365 dni zaczyna lagować — benchmark testy. |
| **coverage-badge** | SVG badge coverage na README | Cosmetic. Dodać po M2 jeśli 80%+ coverage zostaje stabilne. |

### Bezpieczeństwo / DevOps

| Pakiet | Cel | Dlaczego odłożone |
|--------|-----|-------------------|
| **django-otp** | 2FA | M2 ma jeden user (Sebastian admin). W M3 z wieloma userami warto 2FA dla admina. |
| **sentry-sdk** | Error tracking production | M2 jest local dev only. Sentry od momentu deploymentu do prod. |
| **structlog** | Structured logging | Opcja do rozważenia gdy audit log idzie na pełną skalę. |

---

## 7. Hosting / Deployment

### Propozycja M3

- **VPS** (Hetzner / DigitalOcean / Contabo) — ~€5-10/mc.
- **Stack:**
  - Gunicorn (WSGI) + Nginx (reverse proxy) + PostgreSQL + Redis (jeśli Celery).
  - SSL via Let's Encrypt (`certbot`).
- **Alternatywy:**
  - **Fly.io** — Docker-first, darmowa warstwa dla małych projektów.
  - **Railway** — push-to-deploy, dobra dev experience.
  - **PythonAnywhere** — Django-friendly, prosty onboarding.
- **CI/CD:**
  - GitHub Actions workflow (`.github/workflows/ci.yml`):
    - Lint (ruff check + format check).
    - Tests (pytest with coverage).
    - Security scan (bandit / safety check).
    - Deploy on merge do main (SSH deploy lub Docker push).
- **Monitoring:**
  - Sentry dla błędów.
  - Uptime Robot dla monitoringu /healthz endpointa.
  - Healthcheck endpoint w Django views (`/healthz/` → 200 OK + DB ping).

---

## 8. Funkcjonalne rozszerzenia (pomysły spoza kursu)

Propozycje „na wyrost", jeśli Sebastian chce ambitniejszy M3 niż oryginalna lista:

- **Moduł budów (Construction Sites)** — już częściowo w M2 jeśli zdecydujemy zaimplementować TASK 14 z M1 v2 (`ConstructionSite` model z 9-cyfrowym numerem projektu). Rozszerzenie w M3: strony budowy, zdjęcia z budowy, dokumenty (umowy, protokoły).
- **Moduł czasu pracy pracowników** — godzinowe rozliczenia + raportowanie.
- **Moduł materiałów** — analogiczny do WMS `shop/`: katalog materiałów, zamówienia wewnętrzne, FIFO stock. Bardzo duży moduł — raczej M4.
- **Moduł planowania transportów** — analogiczny do WMS `planning/`: transport (scheduled date, cargo) → machine assignment.
- **Moduł zwrotów materiałów** — WMS `returns/` (overshotten panelen). Specyficzny dla branży izolacji, może nie pasować do Planera Maszyn.
- **Import z Excel** — rzeczywiste arkusze od klienta (często bałaganiarskie) → defensywny import jak obecny `machines_db.json`, ale z Excel.
- **Mapa budów** (Leaflet / Google Maps) — pokazuje aktualne lokalizacje maszyn na mapie Polski. Wymaga geocodera (Nominatim, darmowy).
- **Mobile-friendly view** — Tailwind już jest responsive, ale M3 może dodać dedykowane mobile-first flows (quick-scan QR code maszyny → status).
- **Chatbot AI** — moduł konwersacyjny (Pydantic AI + LLM provider) do zapytań o maszyny, rezerwacje i historię serwisową. Wymaga konfiguracji kluczy API w środowisku produkcyjnym.

---

## 9. Zasady stylistyczne utrzymywane z M2

Przy kontynuacji w M3:

- **UI po polsku hardkodowany w M2.** W M3 wprowadzenie `gettext_lazy` + `.po` files — refaktor wszystkich stringów na `_("...")`. To sam w sobie osobny sprint.
- **Kod po angielsku.** Zachować.
- **Django LTS only** (5.2 w M2 → ewentualnie 5.3 w M3 jeśli zostanie ogłoszone jako LTS).
- **Zero zewnętrznych deps produkcyjnych w runtime** jest już porzucone w M2 (mamy Django + kilkanaście pakietów). W M3 zachować minimalizm — każdy nowy pakiet uzasadniony.
- **Alpine Reactive Derived UI State** jako obowiązujący wzorzec dla reaktywnych sekcji (po Wave 13 patternie z WMS).
- **Testy ≥ 80% coverage** — utrzymać.

---

## 10. Co NIE wchodzi w M3 (ostrzeżenie przed planowaniem M3)

Żeby nie było wątpliwości — te rzeczy pojawiły się w dyskusjach o M2 i zostały **świadomie** odłożone poza M3 lub w ogóle poza zakres kursu:

- **Voice agent / chatbot głosowy** (Whisper + ElevenLabs) — pomysł z WMS roadmap M5, nie dotyczy kursu.
- **WhatsApp Business API / Telegram Bot API** (WMS M6) — nie dotyczy.
- **Hilti ON!Track integracja** (WMS M4) — nie dotyczy.
- **Cladseal Optimizer** (WMS `cladseal/`) — branżowy specyfik, nie dotyczy.
- **Moduł shop / stock FIFO** (WMS `shop/`) — możliwy w M4+, ale nie M3.

---

## 11. Propozycje do ewentualnego M3 sprint planu (luźny szkic)

Jeśli M3 ma 8 sprintów (podobnie jak M2), luźny szkic:

- **S1** — i18n foundation + PL/NL/FR/EN `.po` skeleton + `LocaleMiddleware` + przełącznik języka.
- **S2** — RBAC: Django Groups + permission decorators + login flow + profil pracownika.
- **S3** — Audit log middleware + model `AuditLogEntry` + admin page + CSV export.
- **S4** — Email backend + 7 scenariuszy mailingowych + szablony PL/NL.
- **S5** — Raporty: wykorzystanie maszyn, ranking osób, koszty — Chart.js + PDF eksport.
- **S6** — 2FA + password policy + session timeout + CSP hardening do poziomu prod.
- **S7** — Deployment: VPS setup / Fly.io deploy + GitHub Actions CI + Sentry + monitoring.
- **S8** — Testing week (tak jak w M2).

To jest bardzo ambitny M3 — jeśli Sebastian zdecyduje się tylko na podstawowe 5 tematów z harmonogramu, S6-S7 można zmniejszyć albo pominąć.

---

## Na zakończenie

Nie musisz decydować o M3 teraz. Ten dokument zostaje w repo jako punkt odniesienia na czas planowania M3. Jeśli propozycja jest zbyt szeroka albo zbyt wąska — do korekty podczas planowania M3.

> _Notatka z 2026-04-20 — wersje bibliotek do zweryfikowania przed startem M3 (np. Django LTS może się zmienić, nowe releasy)._
