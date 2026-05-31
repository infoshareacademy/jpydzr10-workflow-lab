# JIRA Tasks — Milestone 3: Aplikacja Web Zaawansowana

**Projekt:** Planer Maszyn Budowlanych — system rezerwacji i serwisu maszyn dla firmy **Isocab Construct**.
**Milestone 2 (Aplikacja web — Django):** zakończony ~14.06.2026 (prezentacja przygotowawcza poszła 31.05.2026, prezentacja właściwa za 2 tygodnie).
**Milestone 3 (Aplikacja web zaawansowana):** rozpoczyna się **15.06.2026** (po prezentacji M2), deadline **30.06.2026** (16 dni roboczych — wersja skrocona).
**Pełen oryginalny deadline kursowy:** 09.08.2026, ale plan M3 zamykamy do końca czerwca żeby zostawić lipiec/sierpień na refaktor + ewentualne biznesowe rozszerzenia poza scopem kursu.

---

## Cel Milestone 3

Domknięcie 5 zaplanowanych obszarów M3 z oryginalnego harmonogramu kursu:

1. **Internacjonalizacja** — pełna lokalizacja PL / NL / FR / EN (3 nowe języki, każdy ma być wdrożony chirurgicznie, nie po łebkach).
2. **Mailing transakcyjny** — system wysyłki maili przez Google Workspace SMTP (konto firmowe `info@werkstroomlab.be`), 6 scenariuszy biznesowych.
3. **Audit log** — logowanie wszystkich akcji POST/PUT/DELETE w UI + admin page + eksport CSV + retention policy.
4. **Raporty wizualne** — 4 wykresy Chart.js na nowej stronie `/raporty/` + eksport PDF raportu miesięcznego.
5. **Polish, dokumentacja, bezpieczeństwo** — `django check --deploy` clean, dokumentacja użytkownika końcowego (PDF), demo data refresh, E2E smoke testy.

**Świadome cięcia względem oryginalnych propozycji** (zob. sekcja "Co NIE wchodzi w M3"): hosting odłożony, Celery/Redis/django-channels/2FA/Sentry/Frappe Gantt pomijane jako overkill dla skali projektu.

---

## Konwencje i bezwzględne zasady

Zasady jak w Milestone 2 — bez zmian. Najważniejsze przypomnienia:

- **Język UI:** od M3 wchodzi **i18n PL/NL/FR/EN**. Każdy nowy string MUSI być owinięty w `{% trans %}` / `gettext_lazy`. Stringi nieprzetłumaczone = blocker przy merge.
- **Język kodu:** angielski. Nazwy klas, funkcji, zmiennych, komentarzy.
- **Git workflow:** `feature/m3-sN-<nazwa>` branche → rebase na develop → squash merge do develop → merge developu do main z `--no-ff` (merge commit jako marker sprintu).
- **Commit messages:** `typ: opis` po polsku (ASCII bez diakrytyków, np. "zaktualizowano" zamiast "zaktualizowano"). Bez `--amend` na opublikowanych commitach, bez `--no-verify`.
- **Każdy commit:** wszystkie testy zielone (`uv run pytest -q -n auto`), lint czysty (`uv run ruff check . && uv run ruff format --check .`).
- **Coverage target:** ≥ **95%** (kontynuacja M2 — `fail_under=95.0` w `pyproject.toml`).
- **Każdy merge do develop:** manualna weryfikacja UI w przeglądarce (lokalnie `make run` na :8002) w **każdym z 4 języków** (PL / NL / FR / EN).
- **Magic numbers / strings:** wszystkie w module-level constants.
- **`except Exception` zakazane** — konkretne wyjątki lub komentarz wyjaśniający.
- **TODO zakazane w kodzie** — wszystkie pomysły idą do tego dokumentu jako taski.
- **Push na shared branche (`main`, `develop`):** zwykły non-force push tylko. ZAKAZ `--force`, `--force-with-lease`, `filter-branch`, `filter-repo`, `commit --amend` na opublikowanym commitcie.

---

## Stack — rozszerzenia w M3

Stack M2 zostaje bez zmian. **Nowe paczki dodawane w M3:**

| Warstwa | Pakiet | Wersja minimum | Zastosowanie |
|---------|--------|----------------|--------------|
| Charts | **Chart.js** | **4.x stable** (vendored w `static/vendor/`) | 4 wykresy na stronie `/raporty/` |
| PDF reports | **reportlab** | **>=4.2** (już w stacku, użyte do PDF rezerwacji) | Raport miesięczny PDF |
| Matplotlib (PDF charts) | **matplotlib** | **>=3.9** | Renderowanie wykresów w PDF (server-side, Chart.js to JS-only) |
| Coverage badge | **coverage-badge** | **>=1.1** | SVG badge w README po pytest |

**Bez nowych zewnętrznych zależności:**

- Mailing — `django.core.mail` (wbudowane) z SMTP backendem na Google Workspace
- i18n — `django.utils.translation` (wbudowane) + `gettext` z systemu (`brew install gettext` na macOS, jeśli jeszcze nie ma)
- Audit log — custom middleware + model, **bez** `django-auditlog` (duplikacja z naszą logiką)

**Flatpickr lokalizacje** dodane jako vendored static files:

- `static/vendor/flatpickr-nl.js`
- `static/vendor/flatpickr-fr.js`
- `static/vendor/flatpickr-en.js`
- (`flatpickr-pl.js` już istnieje z M2)

---

## Architektura — co zmienia się w M3

Względem stanu po M2:

```
planer_workflow/                       (root)
├── core/
│   ├── mailing.py                     # NOWE — helper send_localized_mail()
│   ├── middleware.py                  # NOWE — AuditLogMiddleware
│   ├── models.py                      # ZMIANA — dodany AuditLogEntry
│   └── management/commands/
│       ├── prune_audit_log.py         # NOWE
│       ├── send_daily_reminders.py    # NOWE
│       └── send_inspection_alerts.py  # NOWE
├── reports/                           # NOWA app — wykresy + PDF
│   ├── views.py
│   ├── urls.py
│   ├── pdf_generator.py
│   └── tests/
├── accounts/
│   └── models.py                      # ZMIANA — EmployeeProfile.preferred_language
├── locale/                            # ROZSZERZENIE
│   ├── nl/LC_MESSAGES/django.{po,mo}  # 100% tłumaczeń
│   ├── fr/LC_MESSAGES/django.{po,mo}  # 100% tłumaczeń
│   └── en/LC_MESSAGES/django.{po,mo}  # 100% tłumaczeń (z 90% do 100%)
├── templates/
│   ├── emails/                        # NOWE
│   │   ├── base_email.html
│   │   ├── reservation_confirmed.{txt,html}
│   │   ├── reservation_cancelled.{txt,html}
│   │   ├── reservation_reminder.{txt,html}
│   │   ├── inspection_overdue.{txt,html}
│   │   ├── inspection_upcoming.{txt,html}
│   │   └── password_reset.{txt,html}  # OVERRIDE Django default
│   └── reports/
│       └── reports_dashboard.html     # NOWE
├── static/vendor/
│   ├── chart.min.js                   # NOWE — Chart.js 4.x
│   ├── flatpickr-nl.js                # NOWE
│   ├── flatpickr-fr.js                # NOWE
│   └── flatpickr-en.js                # NOWE
├── docs/
│   ├── instrukcja-magazyniera.pdf     # NOWE
│   └── instrukcja-administratora.pdf  # NOWE
├── scripts/
│   └── backup_db.sh                   # NOWE — pg_dump helper
└── .github/badges/
    └── coverage.svg                   # NOWE — auto-generated
```

---

## Harmonogram sprintów

Dwa sprinty tygodniowe + bufor na polish:

| Sprint | Daty | Główne tematy |
|--------|------|---------------|
| **S1** | 15-21.06.2026 (7 dni) | i18n PL/NL/FR/EN pełne + Mailing transakcyjny |
| **S2** | 22-28.06.2026 (7 dni) | Audit log + Raporty Chart.js + PDF |
| **Bufor** | 29-30.06.2026 (2 dni) | Polish, dokumentacja, demo refresh, E2E |

---

## SPRINT 1 (15-21.06.2026) — i18n + Mailing

### Task 1.1 — i18n: pełna lokalizacja PL / NL / FR / EN

**Co robimy:** każdy widoczny string w UI ma 4 wersje językowe. Switcher języka w nav header, datepicker zlokalizowany, formatowanie dat per locale, emaile w języku odbiorcy.

**Plan działania:**

1. Audit istniejącego stanu i18n (commit message `chore: audyt i18n stanu wyjsciowego`):
   ```bash
   uv run python manage.py makemessages -l nl --no-obsolete
   uv run python manage.py makemessages -l fr --no-obsolete
   uv run python manage.py makemessages -l en --no-obsolete
   # Sprawdz ile msgids vs ile przetlumaczonych
   for lang in nl fr en; do
       echo "=== $lang ==="
       msgfmt --statistics locale/$lang/LC_MESSAGES/django.po
   done
   ```

2. Owinąć WSZYSTKIE stringi w templates (`{% trans %}` / `{% blocktrans %}`):
   - `templates/home.html` — KPI cards, sekcja "Dziś w magazynie", wszystkie nagłówki
   - `templates/base.html` — nav, footer, search placeholder
   - `reservations/templates/reservations/*.html` — timeline, legenda, filtry, modal, lista, detail, form
   - `machines/templates/machines/*.html`
   - `service/templates/service/*.html`
   - `accounts/templates/accounts/*.html`
   - `chatbot/templates/chatbot/*.html` — drawer + system messages (NIE prompty AI, te zostają PL bo to wewnętrzna logika modelu)
   - `templates/core/maps.html`
   - `templates/admin/` (override dla unfold — jeśli są)

3. Owinąć stringi w Python:
   - `gettext_lazy` w `models.py` (verbose_name, help_text, choices labels)
   - `gettext_lazy` w `forms.py` (labels, error_messages, help_text)
   - `gettext` w `views.py` (messages.success/error/warning, ValidationError messages)
   - `gettext_lazy` w `services.py` (ValidationError("Adres dostawy jest wymagany.") → `_("Adres dostawy jest wymagany.")`)

4. Wyciągnąć msgids + przetłumaczyć:
   ```bash
   # Generuj/aktualizuj .po
   uv run python manage.py makemessages -l nl -l fr -l en --no-obsolete
   # Edytuj .po manualnie — KAZDY msgid musi miec msgstr
   # (rekomendacja: open Poedit GUI dla wygody, ALE i nano/vim wystarczy)
   uv run python manage.py compilemessages
   ```

5. Dodać `EmployeeProfile.preferred_language` (CharField choices PL/NL/FR/EN, default 'pl'):
   - Migracja `accounts/migrations/00XX_employee_preferred_language.py`
   - Admin: dodać do `EmployeeProfileAdmin.fieldsets`
   - Form: dodać do user edit form

6. Switcher języka w nav header (`templates/base.html`):
   ```html
   <form action="{% url 'set_language' %}" method="post" class="inline">
       {% csrf_token %}
       <input type="hidden" name="next" value="{{ request.path }}">
       <select name="language" onchange="this.form.submit()">
           <option value="pl">PL</option>
           <option value="nl">NL</option>
           <option value="fr">FR</option>
           <option value="en">EN</option>
       </select>
   </form>
   ```
   Zaznaczanie aktualnego języka przez `{% get_current_language as LANG %}` + `{% if LANG == 'nl' %}selected{% endif %}`.

7. Flatpickr locale switching w `static/js/app.js`:
   ```js
   var htmlLang = document.documentElement.lang || 'pl';
   var flatpickrLocaleMap = {
       pl: window.flatpickr.l10ns.pl,
       nl: window.flatpickr.l10ns.nl,
       fr: window.flatpickr.l10ns.fr,
       en: window.flatpickr.l10ns.en  // default English
   };
   window.flatpickr.localize(flatpickrLocaleMap[htmlLang] || flatpickrLocaleMap.pl);
   ```

8. Konfiguracja w `settings/base.py`:
   ```python
   LANGUAGE_CODE = 'pl'
   LANGUAGES = [
       ('pl', _('Polski')),
       ('nl', _('Nederlands')),
       ('fr', _('Francais')),
       ('en', _('English')),
   ]
   LOCALE_PATHS = [BASE_DIR / 'locale']
   USE_I18N = True
   USE_L10N = True  # formatowanie dat/liczb per locale
   ```
   Dodać `django.middleware.locale.LocaleMiddleware` PO `SessionMiddleware`, PRZED `CommonMiddleware`.

**Definition of Done:**

- [ ] `msgfmt --statistics locale/nl/LC_MESSAGES/django.po` zwraca `X translated messages, 0 untranslated, 0 fuzzy` (analogicznie dla `fr`, `en`)
- [ ] `compilemessages` przechodzi bez warningów, `.mo` pliki w repo
- [ ] Switcher języka w nav header działa: klik PL/NL/FR/EN → cała strona przeładowana w tym języku, cookie `django_language` zapisany
- [ ] **Manualny obchód w przeglądarce w 4 językach** (lista checklist do odhaczenia per język):
  - [ ] `/` dashboard (wszystkie KPI cards, sekcja "Dziś w magazynie", linki)
  - [ ] `/rezerwacje/timeline/` (legenda, filtry, KPI period, modal rezerwacji, akcje terminalne, paginacja)
  - [ ] `/rezerwacje/` (lista, filtry, paginacja, sortowanie)
  - [ ] `/rezerwacje/<pk>/` (detail, breadcrumbs, akcje, simple-history widget)
  - [ ] `/rezerwacje/nowa/` (form: labels, placeholders, error messages, help_text, validation messages)
  - [ ] `/maszyny/`, `/maszyny/<uid>/` (lista, detail, historia serwisowa, eksport)
  - [ ] `/budowy/`, `/budowy/<id>/` (lista, detail, mapa)
  - [ ] `/serwis/` (historia serwisowa + raport problemu form)
  - [ ] `/mapy/` (legenda, info BETA, brak-klucza panel)
  - [ ] `/chatbot/` (drawer, placeholdery, history, error messages)
  - [ ] Admin Unfold (nazwy modeli + akcje + filters)
  - [ ] Toast notifications + flash messages
  - [ ] Modale potwierdzeń destrukcyjnych (np. anuluj rezerwację, zakończ)
- [ ] Flatpickr datepicker pokazuje miesiące/dni tygodnia w aktualnym języku UI
- [ ] Daty formatowane per locale: `2026-06-15` (PL), `15 juni 2026` (NL), `15 juin 2026` (FR), `June 15, 2026` (EN) — bez `force_str` ani hardcoded format
- [ ] Email templates (z task 1.2) zlokalizowane — wysyłka maila po `confirm_reservation` używa `with translation.override(user.profile.preferred_language)`
- [ ] Walidacja form: ValidationError messages owinięte w `gettext_lazy`, pokazują się w aktualnym języku UI
- [ ] Testy: `uv run pytest reservations/tests/test_i18n.py -v` — minimum 8 testów (per język: jeden sprawdza tytuł home view, drugi flash message po confirm_reservation)
- [ ] **Acceptance**: użytkownik z `Accept-Language: nl-BE` otwiera aplikację i widzi 100% UI po niderlandzku — ani jednego polskiego stringa (poza nazwami własnymi typu "Isocab Construct", "Wroclaw", UID maszyn)

**Effort estimate:** 5 dni roboczych (najwięcej czasu na tłumaczenia — ~600 msgids × 3 języki = 1800 fraz).

---

### Task 1.2 — Mailing transakcyjny (Google Workspace SMTP)

**Co robimy:** podpinamy SMTP Google Workspace (konto `info@werkstroomlab.be`), tworzymy 6 maili transakcyjnych wysyłanych w 4 językach.

**Setup SMTP Google Workspace:**

1. Wygenerować **App Password** w Google Account:
   - Google Account → Security → 2-Step Verification → App passwords
   - "Select app": Mail, "Select device": Other → "Planer Maszyn Django"
   - Skopiować 16-znakowy kod, zapisać w `.env` jako `EMAIL_HOST_PASSWORD`

2. Rozszerzyć `.env`:
   ```
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=info@werkstroomlab.be
   EMAIL_HOST_PASSWORD=<16-znakowy-app-password>
   DEFAULT_FROM_EMAIL=Planer Maszyn <info@werkstroomlab.be>
   SERVER_EMAIL=info@werkstroomlab.be
   ```

3. `settings/prod.py`:
   ```python
   EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
   ```
   `settings/dev.py` zostaje na console backend (opcjonalnie: flaga `DJANGO_DEV_REAL_EMAIL=1` przełącza na SMTP).

**Moduł `core/mailing.py`:**

```python
def send_localized_mail(template_base, context, to_email, language, attachments=None):
    """Renderuje subject + body w wskazanym jezyku, wysyla async-safe."""
    from django.utils import translation
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    with translation.override(language):
        subject = render_to_string(f'emails/{template_base}_subject.txt', context).strip()
        body_text = render_to_string(f'emails/{template_base}.txt', context)
        body_html = render_to_string(f'emails/{template_base}.html', context)

    msg = EmailMultiAlternatives(subject, body_text, to=[to_email])
    msg.attach_alternative(body_html, 'text/html')
    for att in (attachments or []):
        msg.attach(*att)
    msg.send(fail_silently=False)
```

Wywoływane z `transaction.on_commit(lambda: send_localized_mail(...))` żeby mail nie poszedł jeśli transakcja DB się wycofa.

**6 maili transakcyjnych (P0):**

| # | Trigger | Odbiorca | Język | Szablony |
|---|---------|----------|-------|----------|
| 1 | `confirm_reservation()` | `EmployeeProfile.user.email` osoby `responsible_person` | preferred_language odbiorcy | `reservation_confirmed.{txt,html}` |
| 2 | `cancel_reservation()` | jw. | jw. | `reservation_cancelled.{txt,html}` |
| 3 | cron `send_daily_reminders` (rano) | kierownicy budów których rezerwacja startuje jutro | jw. | `reservation_reminder.{txt,html}` |
| 4 | cron `send_inspection_alerts` (codziennie) | administrator floty (rola Administratorzy) | preferred_language admina | `inspection_overdue.{txt,html}` |
| 5 | cron `send_inspection_alerts` | jw. | jw. | `inspection_upcoming.{txt,html}` (z flagą `inspection_warning_sent_at` na Machine żeby nie spamowac) |
| 6 | Django password reset flow | user requesting reset | preferred_language usera | `password_reset.{txt,html}` (override Django default) |

**Definition of Done:**

- [ ] `.env` rozszerzone o 6 zmiennych EMAIL_*, `.env.example` zaktualizowany (bez prawdziwego App Password)
- [ ] App Password wygenerowane i działa — manualnie z Django shell `send_mail('test', 'body', None, ['info@werkstroomlab.be'])` dochodzi do skrzynki w <30 sek
- [ ] `settings/prod.py` przełączony na SMTP backend, `settings/test.py` na `locmem` (Django test default)
- [ ] Migracja `accounts/migrations/00XX_employee_preferred_language.py` — dodaje pole CharField choices PL/NL/FR/EN default 'pl'
- [ ] `core/mailing.py` z funkcją `send_localized_mail()` + testy unit
- [ ] **24 pliki email templates** (6 maili × 2 wersje (txt, html) × 4 języki = 48 plików? NIE — txt/html w danym języku, ale język = zmienna runtime, nie filename. Czyli: 6 maili × 2 wersje = **12 plików HTML/TXT** + każdy template wewnętrznie używa `{% trans %}` żeby się przełączał per language). Plus 6 subject templates.txt = **18 plików łącznie**.
- [ ] Każdy mail HTML ma branded header (logo + nazwa firmy "Isocab Construct") + footer (kontakt + unsubscribe placeholder)
- [ ] Każdy mail HTML ma plaintext fallback (`EmailMultiAlternatives`)
- [ ] 2 nowe management commands w `core/management/commands/`:
  - `send_daily_reminders.py` — wysyła reminder T-1 day, idempotentne (flag `reminder_sent_at` na Reservation)
  - `send_inspection_alerts.py` — wysyła overdue + upcoming (z flagą żeby nie spamowac)
- [ ] **README.md** rozszerzony o sekcję "Production cron" z entries:
  ```
  0 7 * * * cd /app && uv run python manage.py send_daily_reminders
  0 8 * * * cd /app && uv run python manage.py send_inspection_alerts
  ```
- [ ] **Manualny test każdego z 6 maili w 4 językach = 24 wysyłki** do `info@werkstroomlab.be`:
  - [ ] reservation_confirmed (PL, NL, FR, EN)
  - [ ] reservation_cancelled (PL, NL, FR, EN)
  - [ ] reservation_reminder (PL, NL, FR, EN)
  - [ ] inspection_overdue (PL, NL, FR, EN)
  - [ ] inspection_upcoming (PL, NL, FR, EN)
  - [ ] password_reset (PL, NL, FR, EN)
- [ ] Każdy mail w Gmail Web + Outlook Web:
  - [ ] dostarczalność (Inbox, nie Spam)
  - [ ] HTML renderuje się poprawnie (logo, układ, ciemny motyw kompatybilny)
  - [ ] linki działają (otwierają correct page w app)
  - [ ] plaintext fallback dostępny (View → Show original)
- [ ] Testy: `uv run pytest tests/test_mailing.py -v` — minimum 12 testów:
  - Per mail: render bez crash + zawiera kluczowe pola
  - Per język: subject jest przetłumaczony
  - Backend test: `locmem`
- [ ] **Acceptance**: Sebastian klika "Potwierdź rezerwację" w UI → w ciągu 30 sek dostaje na `info@werkstroomlab.be` mail z poprawnym subject + body w języku ustawionym dla user'a (`preferred_language`), z klikalnym linkiem `https://localhost:8002/rezerwacje/123/` do detalu.

**Effort estimate:** 3 dni roboczych (setup SMTP + 6 maili + crony + testy).

---

## SPRINT 2 (22-28.06.2026) — Audit log + Raporty + Polish

### Task 2.1 — Audit log (custom middleware + model)

**Co robimy:** każda akcja POST/PUT/PATCH/DELETE w UI jest logowana do tabeli `AuditLogEntry`. Admin może filtrować/przeszukiwać/eksportować do CSV. Cron prune'uje wpisy starsze niż 90 dni.

**Plan działania:**

1. Model `core.AuditLogEntry`:
   ```python
   class AuditLogEntry(models.Model):
       user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
       timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
       action = models.CharField(max_length=100, db_index=True)
       object_type = models.CharField(max_length=100, db_index=True)
       object_id = models.CharField(max_length=100, db_index=True)
       object_repr = models.CharField(max_length=200)
       changes = models.JSONField(default=dict, blank=True)
       ip_address = models.GenericIPAddressField(null=True, blank=True)
       user_agent = models.CharField(max_length=300, blank=True)

       class Meta:
           ordering = ['-timestamp']
           indexes = [models.Index(fields=['user', '-timestamp']),
                      models.Index(fields=['object_type', 'object_id'])]
   ```

2. Middleware `core.middleware.AuditLogMiddleware`:
   - Po `AuthenticationMiddleware` w `MIDDLEWARE`
   - Loguje TYLKO requests z method in `{POST, PUT, PATCH, DELETE}` które zwróciły 2xx/3xx
   - `action` derive z `resolve(request.path).url_name`
   - Wyłączenia: paths `/healthz/`, `/static/`, `/admin/login/`, `/i18n/setlang/`, GET-only views

3. Diff capture:
   - Dla update: zapisać pre-state w `request._audit_pre_state` w pre-save signal, porównać z post-state
   - Dla create: serializować wszystkie pola
   - Dla delete: snapshot przed usunięciem

4. Admin page Unfold `/admin/core/auditlogentry/`:
   - List display: timestamp, user, action, object_type, object_repr, ip_address
   - List filters: user, action, object_type, daterange (django-admin built-in DateFieldListFilter)
   - Search: `object_repr`, `user__username`
   - Read-only (nie da się edytować/usuwac z admin — tylko z command line)

5. CSV export:
   - Button "Eksportuj CSV" w admin list view → wszystkie aktualnie filtered wpisy
   - Plik: `audit-log-YYYY-MM-DD.csv`, UTF-8 z BOM (dla Excel)
   - Kolumny: timestamp, user, action, object_type, object_repr, changes_json, ip_address

6. Cron retention:
   - `core/management/commands/prune_audit_log.py` z arg `--older-than 90`
   - Domyślnie 90 dni
   - README cron entry: `0 3 * * 0 cd /app && uv run python manage.py prune_audit_log --older-than 90` (cotygodniowo w niedzielę 3:00)

**Definition of Done:**

- [ ] Model `AuditLogEntry` + migracja
- [ ] Middleware `AuditLogMiddleware` zarejestrowany w `settings/base.py`
- [ ] Wyłączenia działają: GET requests nie loguja, healthz/static/setlang wyłączone (audit: po 100 GET requestach `AuditLogEntry.objects.count() == 0`)
- [ ] Loguje wszystkie 2xx/3xx POST/PUT/PATCH/DELETE z poprawnym `action`, `object_type`, `object_id`
- [ ] `changes` JSONField zawiera diff (pre/post values) dla update, full state dla create, snapshot dla delete
- [ ] Admin page `/admin/core/auditlogentry/` z filtrami (user, action, object_type, daterange) + search po `object_repr`
- [ ] CSV eksport działa: filtered wpisy → plik UTF-8 BOM → otwiera się w Excelu z polskimi znakami niezepsutymi
- [ ] `prune_audit_log --older-than 90` usuwa wpisy starsze niż 90 dni, zwraca count usuniętych
- [ ] IP capture z `request.META.get('HTTP_X_FORWARDED_FOR', request.META['REMOTE_ADDR'])` (split na `,` i first IP)
- [ ] Testy: `uv run pytest core/tests/test_audit_log.py -v` — minimum 8:
  - confirm_reservation tworzy wpis z action='reservation-confirm'
  - cancel_reservation tworzy wpis z `changes.cancellation_reason`
  - anonymous user → `user=None` w wpisie
  - prune usuwa stare wpisy (freezegun)
  - CSV export ma BOM + polskie znaki OK
  - GET nie loguje
  - healthz wyłączony
  - IP capture z X-Forwarded-For
- [ ] **Acceptance**: admin loguje się jako `seba`, otwiera `/admin/core/auditlogentry/`, filtruje "user=seba, daterange=last 7 days, action=reservation-confirm" → widzi listę. Klika "Eksportuj CSV" → otwiera w Excelu, kolumny czytelne, polskie znaki nie zepsute.

**Effort estimate:** 2 dni roboczych.

---

### Task 2.2 — Raporty Chart.js + PDF

**Co robimy:** nowa strona `/raporty/` z 4 wykresami Chart.js + przycisk "PDF raport miesięczny" generujący 1-stronicowy PDF.

**Plan działania:**

1. Nowa app `reports`:
   ```bash
   uv run python manage.py startapp reports
   ```
   Dodać do `INSTALLED_APPS`, URL pattern `path('raporty/', include('reports.urls'))`.

2. Vendor Chart.js 4.x:
   ```bash
   # Weryfikacja wersji
   npm view chart.js time.modified  # czy najnowsza ma >2 tyg?
   curl -o static/vendor/chart.min.js https://cdn.jsdelivr.net/npm/chart.js@4.X.X/dist/chart.umd.min.js
   ```

3. 4 wykresy w `reports/views.py` → `reports_dashboard_view`:

   **Wykres 1 — Wykorzystanie maszyn (%):**
   - Bar chart, oś X = UID maszyn (top 20), oś Y = `(dni_w_terenie / dni_w_okresie) * 100`
   - Okres = ostatnie 30 dni (parametr `?days=30`)
   - Kalkulacja w widoku, dane pchnięte do template jako `json_script`

   **Wykres 2 — Ranking osób (top 10):**
   - Horizontal bar chart
   - Oś X = liczba rezerwacji wpisanych przez osobę (pole `Reservation.person`)
   - Oś Y = nazwiska (top 10)
   - Okres = ostatnie 90 dni

   **Wykres 3 — Koszty serwisowe per miesiąc:**
   - Line chart, oś X = ostatnie 12 miesięcy, oś Y = suma `ServiceRecord.cost`
   - Tooltip: breakdown per typ (`PRZEGLAD`, `NAPRAWA`, `WYMIANA_CZESCI`)

   **Wykres 4 — Pie chart statusów maszyn:**
   - W magazynie / Zarezerwowana / Na budowie / W serwisie / Wycofana
   - Liczebność per status, color-coded (zgodne z timeline legend)

4. PDF eksport raportu miesięcznego:
   - Button "PDF raport za czerwiec 2026" → POST `/raporty/pdf/?month=2026-06`
   - `reports/pdf_generator.py` używa `reportlab` (już w stacku) do layoutu + `matplotlib` do wykresów (server-side render do PNG, wstawione w PDF)
   - 1 strona A4: branding header (logo, nazwa firmy, miesiąc), 4 wykresy (2×2 grid), tabela KPI summary (total rezerwacji, wykorzystanie %, koszty PLN)
   - Plik: `raport-2026-06.pdf`

5. Permissions: `/raporty/` widoczne tylko dla `is_staff` (Kierownicy + Administratorzy):
   ```python
   @method_decorator(staff_member_required, name='dispatch')
   class ReportsDashboardView(View): ...
   ```

6. Lokalizacja: cały widok + labelki wykresów + PDF po PL/NL/FR/EN (tłumaczenia w `.po` z task 1.1).

**Definition of Done:**

- [ ] Chart.js 4.x vendored w `static/vendor/chart.min.js`, wersja zweryfikowana (>2 tyg od release)
- [ ] Nowa app `reports/`, URL `/raporty/`, link w nav header (tylko dla `is_staff`)
- [ ] Wykres 1 (wykorzystanie maszyn) — działa, parametr `?days=N` zmienia okres
- [ ] Wykres 2 (ranking osób) — top 10 sortowane desc, prawidłowe liczby
- [ ] Wykres 3 (koszty serwisowe) — line chart 12 ostatnich miesięcy, tooltip z breakdownem
- [ ] Wykres 4 (statusy maszyn) — pie chart 5 segmentów, kolory zgodne z timeline
- [ ] Wszystkie wykresy responsive (mobile-friendly), reagują na dark mode (color schemes)
- [ ] PDF eksport: button → `raport-2026-06.pdf` z 4 wykresami + KPI table + branded header
- [ ] `/raporty/` zabezpieczone — anonymous → 302 na login, non-staff user → 403
- [ ] Lokalizacja: tytuły wykresów + axis labels + tooltips + PDF po PL/NL/FR/EN
- [ ] Testy: `uv run pytest reports/tests/ -v` — minimum 6:
  - wykres 1 generuje poprawne dane (wykorzystanie z mocked rezerwacji)
  - ranking sortowany desc, top 10 nie więcej
  - koszty sumują się poprawnie z `ServiceRecord.cost`
  - pie chart 5 segmentów
  - PDF generuje się bez crash, content_type='application/pdf'
  - anonymous → 302, non-staff → 403
- [ ] **Acceptance**: Sebastian klika "Raporty" w nav → widzi stronę z 4 wykresami z realnymi danymi z DB → klika "PDF raport za czerwiec 2026" → pobiera plik z ładnym layoutem, drukuje na A4, czytelne.

**Effort estimate:** 3 dni roboczych.

---

### Task 2.3 — Polish, dokumentacja, demo refresh, E2E

**Definition of Done:**

- [ ] **Dokumentacja użytkownika końcowego:**
  - [ ] `docs/instrukcja-magazyniera.pdf` (~5 stron, screenshots z UI): jak zalogować się, jak zarezerwować maszynę, jak potwierdzić, jak zgłosić awarię, jak wydrukować potwierdzenie rezerwacji
  - [ ] `docs/instrukcja-administratora.pdf` (~5 stron): jak dodać użytkownika, jak nadać role/uprawnienia, jak zobaczyć audit log, jak zsynchronizować statusy, jak wyeksportować raport miesięczny
- [ ] **README.md** sekcje:
  - [ ] "Internacjonalizacja" — jak dodać nowy język (`makemessages -l XX`, edycja `.po`, `compilemessages`)
  - [ ] "Mailing" — jak skonfigurować SMTP Google Workspace + App Password
  - [ ] "Production cron" — wszystkie crony (daily_reminders, inspection_alerts, prune_audit_log, run_daily_sync)
  - [ ] "Backup DB" — `scripts/backup_db.sh` + cron entry
- [ ] **Demo data refresh:**
  - [ ] `uv run python manage.py seed_reservations_topup --until 2026-07-30` — żeby timeline na prezentacji M3 nie był pusty po prawej
  - [ ] Sprawdzić że nowe rezerwacje używają istniejących osób (responsible_person) i budów (nie tworzą nowych)
- [ ] **`django check --deploy`** — clean (zero WARNING):
  - [ ] `SECURE_SSL_REDIRECT = True` w prod.py
  - [ ] `SESSION_COOKIE_SECURE = True` w prod.py
  - [ ] `CSRF_COOKIE_SECURE = True` w prod.py
  - [ ] `SECURE_HSTS_SECONDS = 31536000` w prod.py
  - [ ] `SECURE_CONTENT_TYPE_NOSNIFF = True`
  - [ ] `X_FRAME_OPTIONS = 'DENY'`
- [ ] **Performance audit timeline:**
  - [ ] Django Debug Toolbar włączony w dev
  - [ ] Otworzyć `/rezerwacje/timeline/?period=month` z 50+ maszyn × 30 dni
  - [ ] Sprawdzić: <10 queries total, żadne query > 100ms
  - [ ] Jeśli N+1: dodać `select_related('machine', 'site')` / `prefetch_related('reservations')`
- [ ] **Backup strategia DB:**
  - [ ] `scripts/backup_db.sh` z `pg_dump $DATABASE_URL | gzip > backups/$(date +%Y-%m-%d_%H%M).sql.gz`
  - [ ] README cron: `0 2 * * * cd /app && bash scripts/backup_db.sh`
  - [ ] Test manualny: uruchomić skrypt → plik pojawia się w `backups/`, da się rozkompresowac i zaimportować do nowej bazy
- [ ] **Coverage badge:**
  - [ ] `uv run coverage run -m pytest && uv run coverage-badge -f -o .github/badges/coverage.svg`
  - [ ] Badge wstawiony w README na samej górze
  - [ ] Makefile target `make coverage-badge`
- [ ] **Smoke test E2E (Playwright):**
  - [ ] `tests/e2e/test_smoke.py` — minimum 3 scenariusze:
    - [ ] Scenariusz 1: login (seba/seba) → dashboard → click KPI "Aktywne rezerwacje" → lista rezerwacji
    - [ ] Scenariusz 2: timeline → click bar rezerwacji → modal otwiera się → click "Potwierdź" → modal zamyka się + toast success
    - [ ] Scenariusz 3: tworzenie rezerwacji od zera (lista → nowa → form → wybierz maszynę/datę/osobę/budowę → submit → redirect na detail)
  - [ ] `uv run pytest tests/e2e/ --headed=False` przechodzi
  - [ ] Makefile target `make e2e`

**Acceptance:** osoba zewnętrzna (np. ktoś z rodziny lub kolega) dostaje link do aplikacji + `docs/instrukcja-magazyniera.pdf` → potrafi samodzielnie dodać rezerwację bez pytania.

**Effort estimate:** 2 dni roboczych.

---

## Co NIE wchodzi w M3 (świadome cuts — uzasadnienia)

| Cut | Powód |
|-----|-------|
| Hosting (VPS / Fly.io / PythonAnywhere) | Sebastian: "póki co nie hostujemy, wrócimy później". Deployment to potencjalnie 1-2 tyg samego setup'u + monitorowania |
| 2FA / WebAuthn | Overkill dla skali (1 admin + ~5 użytkowników) — single tenant, intranet-style |
| Celery + Redis | Mailing sync wystarczy. Crony do reminderów wystarczają. Celery to overkill |
| django-channels / WebSockets | HTMX wystarcza dla wszystkich realtime potrzeb (potwierdzenia, refresh timeline) |
| Sentry / error monitoring | Bez deploymentu nie ma sensu. Wejdzie razem z hostingiem |
| Frappe Gantt / drag-and-drop timeline | Custom CSS Grid dobrze działa. Frappe to duża zależność (jQuery) |
| Materials/inventory module | Poza scope projektu kursowego |
| Time tracking module | Poza scope projektu kursowego |
| Mobile native app (React Native) | Responsive web wystarczy |
| django-filter, django-ninja, django-mptt, django-select2, crispy-forms | Overengineering — własne implementacje już działają |
| django-import-export | Własny Excel eksport już działa (openpyxl) |
| Mutation testing (mutmut) / property-based (hypothesis dla nowych modułów) | Zostaje na potem — coverage 95% wystarcza |

---

## Pomysły poza scope M3 — kandydaci do rozbudowy biznesowej

Te rzeczy NIE są w planie M3, ale są kandydatami żeby rozważyć po obronie:

- **Inbox/notyfikacje in-app** (oprócz toast HTMX) — model `Notification` + dropdown w nav header z licznikiem unread
- **Saved filters** na liście rezerwacji/maszyn — user-specific, persisted w DB
- **Eksport całej bazy do XLSX** — pełen dump per moduł, alternatywa dla pg_dump dla biznesu
- **Zdjęcia z budowy + dokumenty PDF** (umowy, protokoły odbioru) — extension do `ConstructionSite`
- **Multi-tenancy** (django-tenants) — gdy klient B chce mieć osobną instancję
- **Voice input w chatbocie** (Web Speech API)
- **Mobile PWA** — installable app na telefon z offline support dla rezerwacji read-only

---

## Git flow Sprint 1 (komendy)

```bash
# Start sprintu
git switch develop && git pull --ff-only
git switch -c feature/m3-s1-i18n-pelne

# Praca — małe commity
git add -p && git commit -m "feat(i18n): owijanie stringow w templates/home.html w {% trans %}"
git add -p && git commit -m "feat(i18n): tlumaczenia NL dla reservations/timeline.html"
# ... (przez 5 dni)

# Przed push: rebase na najnowszy develop
git fetch origin && git rebase origin/develop
git push -u origin feature/m3-s1-i18n-pelne --force-with-lease

# Merge do develop (preferowane: squash żeby develop był czysty)
git switch develop && git pull --ff-only
git merge --squash feature/m3-s1-i18n-pelne
git commit -m "feat(M3-S1): i18n pelna lokalizacja PL/NL/FR/EN + flatpickr per-locale"
git push origin develop

# Po pełnym sprincie: develop → main z merge commit
git switch main && git pull --ff-only
git merge --no-ff develop -m "merge: M3 Sprint 1 — i18n + mailing"
git push origin main

# Cleanup
git push origin --delete feature/m3-s1-i18n-pelne
git branch -d feature/m3-s1-i18n-pelne
```

Analogicznie dla `feature/m3-s1-mailing`, `feature/m3-s2-audit-log`, `feature/m3-s2-raporty`, `feature/m3-s2-polish`.

---

## Definition of Done — cały Milestone 3

Przed zakończeniem M3 wszystko poniżej musi być zielone:

- [ ] Wszystkie 5 zaplanowanych obszarów zakończone (i18n, mailing, audit log, raporty, polish)
- [ ] `uv run pytest -q -n auto` — 100% pass, coverage ≥ 95%
- [ ] `uv run ruff check . && uv run ruff format --check .` — clean
- [ ] `uv run python manage.py check --deploy` — clean (zero WARNING)
- [ ] Manualny walk-through w przeglądarce po wszystkich widokach × 4 języki = 4 pełne obchody UI
- [ ] 24 maile transakcyjne wysłane manualnie do `info@werkstroomlab.be`, każdy zweryfikowany w Gmail Web
- [ ] Audit log działa, CSV eksport pobrany i otwarty w Excelu
- [ ] Raporty: 4 wykresy renderują się, PDF generuje się
- [ ] Dokumentacja: 2 PDF instrukcji + README sekcje (i18n, mailing, cron, backup)
- [ ] Demo data: timeline ma rezerwacje sięgające do 2026-07-30
- [ ] Coverage badge w README
- [ ] E2E Playwright: 3 scenariusze pass
- [ ] Wszystko zmergowane do `main` przez `--no-ff` z merge commitami markującymi sprints

---

## Changelog tego dokumentu

| Data | Event |
|------|-------|
| 2026-06-01 | Utworzony jako konkretny plan zaplecza dla M3 (16 dni roboczych: 15-30.06.2026). Bazuje na audycie agentowym `NOTES_FOR_MILESTONE_3.md` z 2026-04-20, ale ze świadomymi cięciami (zob. sekcja "Co NIE wchodzi w M3") + dostosowaniem decyzji biznesowych: pełne 4 języki PL/NL/FR/EN, mailing przez Google Workspace `info@werkstroomlab.be`, hosting odłożony. |
