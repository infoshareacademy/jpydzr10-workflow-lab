# JIRA Tasks — Milestone 3: Aplikacja Web Zaawansowana

**Projekt:** Planer Maszyn Budowlanych — system rezerwacji i serwisu maszyn dla firmy **BudMech**.
**Milestone 2 (Aplikacja web — Django):** zakończony ~14.06.2026 (prezentacja przygotowawcza poszła 31.05.2026, prezentacja właściwa za 2 tygodnie).
**Milestone 3 (Aplikacja web zaawansowana):** rozpoczyna się **15.06.2026** (po prezentacji M2), deadline **30.06.2026** (16 dni roboczych — wersja skrocona).
**Pełen oryginalny deadline kursowy:** 09.08.2026, ale plan M3 zamykamy do końca czerwca żeby zostawić lipiec/sierpień na refaktor + ewentualne biznesowe rozszerzenia poza scopem kursu.

---

## Cel Milestone 3

Domknięcie obszarów M3 z oryginalnego harmonogramu kursu **+ rozszerzenia o wow-faktor** (zgodnie z decyzją 01.06.2026 po audycie adwokata diabła):

1. **Internacjonalizacja** — pełna lokalizacja PL / EN (3 nowe języki, chirurgicznie). **Plurals (3 formy w PL), waluty (EUR default, PLN dla PL), formatowanie liczb i numerów telefonów per locale.**
2. **Mailing transakcyjny** — Google Workspace SMTP (`info@budmech.pl`), 6 scenariuszy biznesowych. **Idempotency, unsubscribe (GDPR), bounce log, dark mode Outlook, preview view, Mailpit w dev.**
3. **2FA (TOTP)** — `django-otp` + QR code dla wszystkich `is_staff` użytkowników. Recovery codes. OWASP A07:2021 compliance.
4. **Audit log** — middleware + `AuditLogEntry` + admin + CSV + retention 90 dni + GDPR erasure obejmuje audit.
5. **Raporty wizualne** — 4 wykresy Chart.js + PDF raport miesięczny (server-side matplotlib) + lokalizacja PL/EN.
6. **Accessibility (WCAG 2.1 AA)** — pełen audit przez Axe DevTools, fixy kontrastów, focus rings, ARIA labels, skip links, keyboard nav. **European Accessibility Act compliance** (od 28.06.2025 wymagane prawem dla nowych app w EU).
7. **CI/CD pipeline** — GitHub Actions: pytest + ruff + coverage badge + bandit + safety (CVE scan deps). **Bez deployment** — sama infrastruktura testowa.
8. **GDPR essentials** — privacy policy page, cookie notice, data export endpoint, anonymize obejmuje audit log.
9. **Polish, dokumentacja, bezpieczeństwo** — `django check --deploy` clean, custom error pages 404/500/403, ERD + 5 ADR (Architecture Decision Records), 2 PDF instrukcje użytkownika, demo data refresh, E2E Playwright + 5 pytest-bdd Gherkin scenariusze, Lighthouse audit, backup restore fire drill.

**Waluta domyślna:** **EUR** (Sebastian operuje w Belgii). Pole `currency` na `ServiceRecord.cost`. Wyświetlanie w UI per locale (EN → EUR z formatem locale, PL → PLN z formatem PL).

**Świadome cięcia** (zob. sekcja "Co NIE wchodzi w M3"): hosting odłożony, Celery/Redis/django-channels/Sentry/Frappe Gantt — overkill. **2FA NIE jest już cuts** (przeniesione do scope).

---

## Konwencje i bezwzględne zasady

Zasady jak w Milestone 2 — bez zmian. Najważniejsze przypomnienia:

- **Język UI:** od M3 wchodzi **i18n PL/EN**. Każdy nowy string MUSI być owinięty w `{% trans %}` / `gettext_lazy`. Stringi nieprzetłumaczone = blocker przy merge.
- **Język kodu:** angielski. Nazwy klas, funkcji, zmiennych, komentarzy.
- **Git workflow:** `feature/m3-sN-<nazwa>` branche → rebase na develop → squash merge do develop → merge developu do main z `--no-ff` (merge commit jako marker sprintu).
- **Commit messages:** `typ: opis` po polsku (ASCII bez diakrytyków, np. "zaktualizowano" zamiast "zaktualizowano"). Bez `--amend` na opublikowanych commitach, bez `--no-verify`.
- **Każdy commit:** wszystkie testy zielone (`uv run pytest -q -n auto`), lint czysty (`uv run ruff check . && uv run ruff format --check .`).
- **Coverage target:** ≥ **95%** (kontynuacja M2 — `fail_under=95.0` w `pyproject.toml`).
- **Każdy merge do develop:** manualna weryfikacja UI w przeglądarce (lokalnie `make run` na :8002) w **każdym z 2 języków** (PL / EN).
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
| PDF reports | **reportlab** | **>=4.2** (już w stacku) | Raport miesięczny PDF |
| Matplotlib (PDF charts) | **matplotlib** | **>=3.9** | Renderowanie wykresów do PNG dla PDF (server-side) |
| Coverage badge | **coverage-badge** | **>=1.1** | SVG badge w README po pytest |
| **2FA** | **django-otp** | **>=1.5** | TOTP + recovery codes |
| **2FA — QR codes** | **qrcode[pil]** | **>=7.4** | Generowanie QR do enrolmentu w Google Authenticator |
| **Telefony** | **phonenumbers** + **django-phonenumber-field** | **>=8.13** / **>=8.0** | Walidacja + formatowanie per locale (+48, +32, +33, +44) |
| **Waluty** | **py-moneyed** + **django-money** | **>=3.0** / **>=3.5** | Pole `Money` (amount + currency code) na `ServiceRecord.cost` z EUR default |
| **Security scan deps** | **safety** lub **pip-audit** | latest | CVE scan w CI |
| **Security scan kod** | **bandit** | **>=1.7** | Hardcoded secrets, weak crypto, SQL injection patterns |
| **ERD** | **django-extensions** | **>=3.2** | `graph_models -a -o docs/erd.png` (Graphviz wymagany) |
| **Local dev SMTP** | **Mailpit** | **latest** (Docker image) | Lokalny SMTP server + UI podglądu w dev (zamiast console backend) |

**Bez nowych zewnętrznych zależności:**

- Mailing produkcyjny — `django.core.mail` (wbudowane) z SMTP backendem na Google Workspace
- i18n — `django.utils.translation` (wbudowane) + `gettext` z systemu (`brew install gettext`)
- Audit log — custom middleware + model, **bez** `django-auditlog` (duplikacja)
- a11y audit — **Axe DevTools browser extension** (Chrome/Firefox, free) + manualny checklist WCAG 2.1 AA

**Flatpickr lokalizacje** dodane jako vendored static files (`static/vendor/flatpickr-{nl,fr,en}.js`). `flatpickr-pl.js` już istnieje z M2.

**System binaries do zainstalowania jednorazowo:**

```bash
brew install gettext graphviz  # i18n compilation + ERD generation
```

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
| **S1** | 15-21.06.2026 (7 dni) | i18n PL/EN pełne (+plurals/EUR/phones) + Mailing (+idempotency/unsubscribe/Mailpit) + **2FA TOTP** |
| **S2** | 22-28.06.2026 (7 dni) | Audit log + Raporty Chart.js + PDF + **równolegle: a11y/CI/security/GDPR z 2.3** |
| **Bufor** | 29-30.06.2026 (2 dni) | Pełen polish (2.3.A-J): custom errors, ERD/ADR, backup restore drill, bdd, Lighthouse, dokumentacja PDF, demo refresh, E2E |

---

## SPRINT 1 (15-21.06.2026) — i18n + Mailing

### Task 1.1 — i18n: pełna lokalizacja PL / EN

> **Zmiana zakresu 2026-06-22:** i18n = **2 języki (PL + EN)**, zredukowane z pierwotnych 4 (NL/FR odpadają — nieużywane). Wymóg „absolutnie wszystko przetłumaczone + zweryfikowane w UI" pozostaje **bez zmian** — zmieniła się wyłącznie liczba języków.

**Co robimy:** każdy widoczny string w UI ma 2 wersje językowe (PL/EN). Switcher języka w nav header, datepicker zlokalizowany, formatowanie dat per locale, emaile w języku odbiorcy.

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

5. Dodać `EmployeeProfile.preferred_language` (CharField choices PL/EN, default 'pl'):
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

- [ ] `msgfmt --statistics locale/en/LC_MESSAGES/django.po` zwraca `X translated messages, 0 untranslated, 0 fuzzy` (analogicznie dla `pl`)
- [ ] `compilemessages` przechodzi bez warningów, `.mo` pliki w repo
- [ ] Switcher języka w nav header działa: klik PL/EN → cała strona przeładowana w tym języku, cookie `django_language` zapisany
- [ ] **Manualny obchód w przeglądarce w 2 językach** (lista checklist do odhaczenia per język):
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
- [ ] **PLURALS audit** — każde KPI/info z liczbą używa `{% blocktrans count counter=n %}` (PL ma 3 formy: `1 maszyna / 2-4 maszyny / 5 maszyn`):
  - [ ] `home.html` KPI ("Aktywne rezerwacje", "Dostępne maszyny", "Przeglądy")
  - [ ] timeline period KPI ("Rezerwacji w okresie", "Oczekuje", "Potwierdzone", "Maszyny")
  - [ ] flash messages typu "Zaktualizowano X rezerwacji"
  - [ ] Test plurals: `pytest tests/test_i18n_plurals.py` — minimum 4 testy (1/2/5/0 maszyn po PL)
- [ ] **WALUTY (EUR default)** — nowy model field + formatowanie:
  - [ ] `pip add django-money py-moneyed` + migracja `ServiceRecord.cost` `Decimal` → `MoneyField(default_currency='EUR')`
  - [ ] Domyślnie EUR dla wszystkich nowych rekordów. PLN dla istniejących (data migration ustawia PLN na rekordach sprzed 01.06.2026)
  - [ ] `settings/base.py`: `DEFAULT_CURRENCY = 'EUR'`, `CURRENCIES = ('EUR', 'PLN', 'GBP', 'USD')`
  - [ ] Wyświetlanie: `{{ record.cost|intcomma }} {{ record.cost.currency }}` z prefixem/sufixem per locale (PL = `1 234,56 PLN`, NL = `€ 1.234,56`, FR = `1 234,56 €`, EN = `€1,234.56`)
  - [ ] Raport miesięczny (Task 2.2) sumuje per waluta osobno (zero auto-konwersji — brak FX rates w M3)
- [ ] **TELEFONY per locale** — phonenumbers lib:
  - [ ] `pip add phonenumbers django-phonenumber-field`
  - [ ] `EmployeeProfile.phone` migrowane na `PhoneNumberField`
  - [ ] Walidacja: numer musi być valid dla wybranego kraju (`+48 ...` dla PL, `+32 ...` dla BE, `+33 ...` dla FR, `+44 ...` dla EN)
  - [ ] Wyświetlanie sformatowane per locale (`+48 123 456 789`)
- [ ] **Formatowanie dat/liczb per locale** (django USE_L10N=True już ustawione, ale audit):
  - [ ] `2026-06-15` (PL ISO) / `15 juni 2026` (NL) / `15 juin 2026` (FR) / `June 15, 2026` (EN)
  - [ ] `1 234,56` (PL/EN) vs `1,234.56` (EN)
- [ ] Testy: `uv run pytest reservations/tests/test_i18n.py -v` — minimum 10 testów (per język: tytuł home view + flash message + plural form + currency format + date format)
- [ ] **Acceptance**: użytkownik z `Accept-Language: en` otwiera aplikację i widzi 100% UI po angielsku — ani jednego polskiego stringa (poza nazwami własnymi typu "BudMech", "Wroclaw", UID maszyn). Koszty serwisowe wyświetlają się w EUR z formatem locale.

**Effort estimate:** 5 dni roboczych (~600 msgids × 3 języki = 1800 fraz + plurals + currency migration + phones).

---

### Task 1.2 — Mailing transakcyjny (Google Workspace SMTP)

**Co robimy:** podpinamy SMTP Google Workspace (konto `info@budmech.pl`), tworzymy 6 maili transakcyjnych wysyłanych w 2 językach.

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
   EMAIL_HOST_USER=info@budmech.pl
   EMAIL_HOST_PASSWORD=<16-znakowy-app-password>
   DEFAULT_FROM_EMAIL=Planer Maszyn <info@budmech.pl>
   SERVER_EMAIL=info@budmech.pl
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
- [ ] App Password wygenerowane i działa — manualnie z Django shell `send_mail('test', 'body', None, ['info@budmech.pl'])` dochodzi do skrzynki w <30 sek
- [ ] `settings/prod.py` przełączony na SMTP backend, `settings/test.py` na `locmem` (Django test default)
- [ ] Migracja `accounts/migrations/00XX_employee_preferred_language.py` — dodaje pole CharField choices PL/EN default 'pl'
- [ ] `core/mailing.py` z funkcją `send_localized_mail()` + testy unit
- [ ] **24 pliki email templates** (6 maili × 2 wersje (txt, html) × 2 języki = 24 plików? NIE — txt/html w danym języku, ale język = zmienna runtime, nie filename. Czyli: 6 maili × 2 wersje = **12 plików HTML/TXT** + każdy template wewnętrznie używa `{% trans %}` żeby się przełączał per language). Plus 6 subject templates.txt = **18 plików łącznie**.
- [ ] Każdy mail HTML ma branded header (logo + nazwa firmy "BudMech") + footer (kontakt + unsubscribe placeholder)
- [ ] Każdy mail HTML ma plaintext fallback (`EmailMultiAlternatives`)
- [ ] 2 nowe management commands w `core/management/commands/`:
  - `send_daily_reminders.py` — wysyła reminder T-1 day, idempotentne (flag `reminder_sent_at` na Reservation)
  - `send_inspection_alerts.py` — wysyła overdue + upcoming (z flagą żeby nie spamowac)
- [ ] **README.md** rozszerzony o sekcję "Production cron" z entries:
  ```
  0 7 * * * cd /app && uv run python manage.py send_daily_reminders
  0 8 * * * cd /app && uv run python manage.py send_inspection_alerts
  ```
- [ ] **Manualny test każdego z 6 maili w 2 językach = 12 wysyłek** do `info@budmech.pl`:
  - [ ] reservation_confirmed (PL, EN)
  - [ ] reservation_cancelled (PL, EN)
  - [ ] reservation_reminder (PL, EN)
  - [ ] inspection_overdue (PL, EN)
  - [ ] inspection_upcoming (PL, EN)
  - [ ] password_reset (PL, EN)
- [ ] Każdy mail w Gmail Web + Outlook Web:
  - [ ] dostarczalność (Inbox, nie Spam)
  - [ ] HTML renderuje się poprawnie (logo, układ, ciemny motyw kompatybilny)
  - [ ] linki działają (otwierają correct page w app)
  - [ ] plaintext fallback dostępny (View → Show original)
- [ ] Testy: `uv run pytest tests/test_mailing.py -v` — minimum 12 testów:
  - Per mail: render bez crash + zawiera kluczowe pola
  - Per język: subject jest przetłumaczony
  - Backend test: `locmem`
- [ ] **Acceptance**: Sebastian klika "Potwierdź rezerwację" w UI → w ciągu 30 sek dostaje na `info@budmech.pl` mail z poprawnym subject + body w języku ustawionym dla user'a (`preferred_language`), z klikalnym linkiem `https://localhost:8002/rezerwacje/123/` do detalu.

### Sub-zadania robustness (dodane po audycie adwokata diabła 01.06.2026):

- [ ] **IDEMPOTENCY crons** — chroni przed dublami przy retry / race condition:
  - [ ] `Reservation.reminder_sent_at` (DateTimeField, nullable). `send_daily_reminders` sprawdza WHERE `reminder_sent_at IS NULL` i ustawia po wysyłce w tej samej transakcji
  - [ ] `Machine.inspection_warning_sent_at` (DateTimeField, nullable). `send_inspection_alerts` upcoming sprawdza flagę, resetuje po przejściu z warning → ok (po przeglądzie)
  - [ ] Test: uruchom cron 3× pod rząd → tylko 1 mail per reservation/machine
- [ ] **UNSUBSCRIBE LINK (GDPR Article 7)** — każdy mail transakcyjny musi mieć:
  - [ ] Footer link `Wypisz się` / `Uitschrijven` / `Se désinscrire` / `Unsubscribe` → URL `/account/email-preferences/?token=<HMAC-signed>`
  - [ ] Widok `email_preferences_view` z formem (toggle per typ maila: reminders, alerts, marketing)
  - [ ] `EmployeeProfile.email_opt_outs` (JSONField) — list typów maili na ktore user się wypisał
  - [ ] `send_localized_mail()` sprawdza opt-out przed wysłaniem, skip jeśli opted-out (oprócz security-critical jak `password_reset`)
- [ ] **BOUNCE LOG (minimalny)** — `core.BounceLog` model:
  - [ ] Pola: timestamp, recipient_email, error_message, retry_count
  - [ ] Try/except wokół `msg.send()` w `send_localized_mail` — łap `smtplib.SMTPRecipientsRefused`, `SMTPDataError`, loguj do BounceLog
  - [ ] Admin page do przeglądania bounces (filtr po email + daterange)
- [ ] **DARK MODE w mailu HTML** — Outlook desktop 2019+ ignoruje `<meta name="color-scheme">`:
  - [ ] `<style>` block z `[data-ogsc]` selektorami dla Outlook ciemnego trybu
  - [ ] Test w Gmail (web ciemny), Outlook Web, Outlook Desktop ciemny
- [ ] **EMAIL PREVIEW VIEW (dev tool)** — `core/views.py` `email_preview_view`:
  - [ ] URL `/admin/preview-email/?template=reservation_confirmed&lang=nl`
  - [ ] Wyświetla renderowany HTML w iframe + plaintext fallback + subject
  - [ ] Wymaga `is_staff` + DEBUG=True (nigdy w prod)
  - [ ] Lista wszystkich 6 maili × 2 języki = 12 przycisków preview
- [ ] **MAILPIT w dev** (zamiast console backend):
  - [ ] Dodać do `docker-compose.yml` service `mailpit`:
    ```yaml
    mailpit:
      image: axllent/mailpit:latest
      ports:
        - "1025:1025"  # SMTP
        - "8025:8025"  # Web UI
    ```
  - [ ] `settings/dev.py`: `EMAIL_HOST='localhost'`, `EMAIL_PORT=1025`, `EMAIL_USE_TLS=False`
  - [ ] README: "wszystkie maile w dev lądują w Mailpit UI: http://localhost:8025"
- [ ] **Acceptance**: po wysłaniu reminder cron 3× pod rząd → 1 mail w skrzynce (idempotency). Klik "Wypisz się" w mailu → strona preferencji, toggle off → następny cron skip tego usera. Mailpit UI w dev pokazuje wszystkie testowe maile.

**Effort estimate:** 3 dni roboczych (setup SMTP + 6 maili + crony + testy + robustness).

---

### Task 1.3 — 2FA (Two-Factor Authentication) — **NEW po audycie 01.06.2026**

**Co robimy:** wszyscy `is_staff` użytkownicy muszą skonfigurować 2FA TOTP (Google Authenticator / 1Password / Authy). Recovery codes na wypadek utraty telefonu. **OWASP A07:2021 compliance + wow faktor dla nauczyciela.**

**Plan działania:**

1. Instalacja:
   ```bash
   uv add django-otp qrcode[pil]
   ```
   `INSTALLED_APPS`: dodać `django_otp`, `django_otp.plugins.otp_totp`, `django_otp.plugins.otp_static` (recovery codes).
   `MIDDLEWARE`: dodać `django_otp.middleware.OTPMiddleware` PO `AuthenticationMiddleware`.

2. Migracje:
   ```bash
   uv run python manage.py migrate
   ```

3. Custom login flow:
   - Po standardowym `LoginView` (username + password) → redirect na `/account/2fa/verify/`
   - Tam user wpisuje 6-cyfrowy token z aplikacji authenticatora → walidacja przez `TOTPDevice.verify_token()`
   - Sukces → `request.session['otp_device_id'] = device.id` + redirect na `next` URL
   - Jeśli user nie ma jeszcze skonfigurowanego device → `/account/2fa/setup/`

4. Setup flow (`/account/2fa/setup/`):
   - Wygeneruj `TOTPDevice` (unconfirmed)
   - Wyrenderuj QR code (base64-encoded PNG) z `provisioning_uri()` (otpauth:// URI)
   - User skanuje QR → wpisuje pierwszy token żeby potwierdzić (`device.confirm_device(token)`)
   - Po confirmie: wygeneruj 10 recovery codes (`StaticToken`), pokaż user'owi RAZ (z guzikiem "Pobierz jako TXT"), zapisz hash w DB
   - Pokaż info "zachowaj te kody w bezpiecznym miejscu, są wyświetlone tylko raz"

5. Wymuszenie 2FA dla `is_staff`:
   - Decorator `@otp_required` lub middleware który sprawdza `request.user.is_verified()` (django-otp) dla wszystkich views z `is_staff` permission
   - Jeśli `is_staff` user się loguje BEZ 2FA setup → forced redirect na `/account/2fa/setup/`
   - Wyjątki: `/account/logout/`, statyki, healthz

6. Disable 2FA flow (dla admina jeśli user zgubił telefon + recovery codes):
   - Tylko `is_superuser` może wyłączyć 2FA innemu userowi z admin panelu
   - Audit log entry: `action='2fa-disabled-by-admin'` z `object_id=target_user.id`

7. UI:
   - Karta "Bezpieczeństwo" w `/account/profile/` z toggle "2FA aktywne / nieaktywne"
   - Button "Wygeneruj nowe recovery codes" (unieważnia stare)

**Definition of Done:**

- [ ] `django-otp` + `qrcode[pil]` zainstalowane, migracje przeszły
- [ ] User `seba` (is_staff) loguje się → forced redirect na `/account/2fa/setup/`
- [ ] Setup: QR code wyświetla się poprawnie, skan w Google Authenticator działa, pierwszy token confirmuje device
- [ ] Po setup: 10 recovery codes wyświetlonych RAZ z guzikiem download TXT, hash zapisany w DB
- [ ] Login: po username/password → `/account/2fa/verify/` → wpisanie 6-cyfrowego tokena → sukces → redirect na `next`
- [ ] Recovery code działa: user zamiast tokena wpisuje recovery code (one-time), system go akceptuje + unieważnia (token nie do reuse)
- [ ] Wszystkie `is_staff` views chronione `@otp_required` lub middleware (404/302 do `/account/2fa/setup/` jeśli user nie zweryfikowany)
- [ ] `is_superuser` może wyłączyć 2FA innemu userowi z admin (z audit log entry)
- [ ] Karta "Bezpieczeństwo" w `/account/profile/` z toggle, guzik "Nowe recovery codes"
- [ ] **Lokalizacja**: setup/verify/recovery codes pages po PL/EN
- [ ] **Backup codes dla demo account** (seba): zapisane w lokalnym pliku notatek poza repo, żeby nie zgubic na prezentacji
- [ ] Testy: `pytest accounts/tests/test_2fa.py -v` — minimum 8 (setup flow, verify flow z prawidłowym tokenem, verify z błędnym tokenem, recovery code one-time, force redirect dla is_staff bez 2FA, admin disable 2FA innego usera tworzy audit log entry, lokalizacja setup page po NL, password reset NIE wymaga 2FA — bo user zalogowany dopiero później)
- [ ] **Acceptance**: nauczyciel widzi login → username/password → 6-cyfrowy kod z Google Authenticator → wchodzi do app. Próba pominięcia 2FA = niemożliwa. Recovery codes do downloadu jako TXT na wypadek utraty telefonu.

**Effort estimate:** 1 dzień roboczy.

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

6. Lokalizacja: cały widok + labelki wykresów + PDF po PL/EN (tłumaczenia w `.po` z task 1.1).

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
- [ ] Lokalizacja: tytuły wykresów + axis labels + tooltips + PDF po PL/EN
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

### Task 2.3 — Polish, a11y, CI, GDPR, dokumentacja — **rozszerzony po audycie 01.06.2026**

**Cel:** wszystkie elementy "wow factor 11/10" które plan podstawowy pomijał.

#### 2.3.A — Accessibility (WCAG 2.1 AA) — **EU compliance + wow factor**

European Accessibility Act (obowiązujący od 28.06.2025 dla nowych app w EU) wymaga zgodności z WCAG 2.1 AA.

- [ ] **Axe DevTools audit** każdej kluczowej strony (login, dashboard, timeline, lista rezerwacji, detail, form rezerwacji, mapy, raporty) — **zero violations level AA**
- [ ] **Kontrasty** (tailwind sprawdzić w dark mode i light mode):
  - [ ] Tekst regular ≥4.5:1 vs background
  - [ ] Tekst large (>=18px lub >=14px bold) ≥3:1
  - [ ] Komponenty UI (border, focus rings) ≥3:1
- [ ] **Focus rings widoczne** na każdym interactive element (button, link, input, select, textarea, modal close). `:focus-visible` outline w Tailwind config
- [ ] **ARIA labels** na ikonach-only buttons (np. close X w modalu, ikony w nav)
- [ ] **Skip links** — `<a href="#main">Pomiń nawigację</a>` na top każdej strony (visible on :focus)
- [ ] **Keyboard navigation** — pełna ścieżka bez myszy:
  - [ ] Tab order zgodny z visual order
  - [ ] Modale: focus trap (Alpine focus plugin już mamy) + ESC zamyka
  - [ ] Dropdowny (Alpine x-show): Enter open, ESC close, arrow keys navigate
- [ ] **Screen reader compatibility** — test z VoiceOver (macOS):
  - [ ] Wszystkie obrazy mają `alt=""` (decorative) lub opisowy alt
  - [ ] Form errors anonsowane przez `aria-live="polite"` lub `role="alert"`
  - [ ] Toast notifications mają `role="status"` / `aria-live`
  - [ ] Tabele mają `<th scope="col">` + `<caption>`
- [ ] **Heading hierarchy** — h1 → h2 → h3 bez skoków
- [ ] **`prefers-reduced-motion`** — wszystkie Alpine transitions sprawdzić, dodać media query w global CSS:
  ```css
  @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
  }
  ```
- [ ] **Lokalizacja a11y attributów** — `aria-label`, `<title>`, alt texts po PL/EN
- [ ] Testy: `pytest tests/test_a11y.py` — minimum 5 (skip link present, focus visible CSS, aria-labels na key buttons, heading hierarchy, reduced motion CSS)

**Effort:** 1 dzień.

#### 2.3.B — CI/CD (GitHub Actions) — **bez deployment**

Pipeline który chroni przed regresjami na każdy push, **bez** serwera produkcyjnego.

- [ ] `.github/workflows/ci.yml`:
  ```yaml
  on: [push, pull_request]
  jobs:
    test:
      runs-on: ubuntu-latest
      services:
        postgres: { image: postgres:16, env: {...}, ports: ['5432:5432'] }
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
        - run: uv sync --frozen
        - run: uv run ruff check . && uv run ruff format --check .
        - run: uv run python manage.py migrate
        - run: uv run pytest -n auto --cov --cov-report=xml --cov-fail-under=95
        - run: uv run bandit -r . -x tests/,migrations/
        - run: uv run safety check --json || true  # warning, nie blocker
        - uses: codecov/codecov-action@v4  # opcjonalne
  ```
- [ ] Coverage badge auto-generated po pytest, commitowany do `.github/badges/coverage.svg`
- [ ] **Status check w PR-ach** — green checkmark obok każdego commita
- [ ] README "Build status" badge na top: ![CI](https://github.com/.../workflows/ci/badge.svg)
- [ ] **Acceptance**: push do feature branch → automatyczny CI run → zielone checki w 2-3 min

**Effort:** 0.5 dnia.

#### 2.3.C — Security scan (bandit + safety + CSP audit)

- [ ] `uv add --dev bandit safety` (lub `pip-audit` jako alternatywa)
- [ ] `bandit -r . -x tests/,migrations/` — naprawić wszystkie HIGH severity findings:
  - [ ] Brak `assert` w produkcyjnym kodzie (Bandit B101)
  - [ ] Brak `subprocess` z `shell=True` (B602)
  - [ ] Brak `pickle.load` z untrusted source (B301)
  - [ ] Brak hardcoded passwords (B105/B106)
- [ ] `safety check` — naprawić wszystkie CVE w deps (lub upgrade do non-vulnerable wersji)
- [ ] **CSP audit** — sprawdzić że nasze `CSP_NONCE` setup faktycznie blokuje inline scripts bez nonce:
  - [ ] Otworzyć DevTools → Console → szukać "Content Security Policy" violations
  - [ ] Wszystkie inline `<script>` muszą mieć `nonce="{{ CSP_NONCE }}"`
  - [ ] Wszystkie inline `<style>` analogicznie
- [ ] **Acceptance**: `bandit -r .` zero HIGH, `safety check` clean, CSP zero violations w przeglądarce

**Effort:** 0.3 dnia.

#### 2.3.D — GDPR essentials

- [ ] **Privacy Policy page** `/legal/privacy/` — 1 strona statyczna z sekcjami:
  - [ ] Kto jest administratorem danych (firma Sebastian'a)
  - [ ] Jakie dane zbieramy (imię, email, telefon, rezerwacje)
  - [ ] Po co (zarządzanie wypożyczeniami)
  - [ ] Jak długo (audit log 90 dni, dane konta do żądania usunięcia)
  - [ ] Prawa użytkownika (dostęp, sprostowanie, usunięcie, sprzeciw, przenośność)
  - [ ] Kontakt (`info@budmech.pl`)
  - [ ] Lokalizacja po PL/EN
- [ ] **Cookie notice** — minimalistyczny banner (Alpine.js, dismissable, zapamiętany w localStorage):
  - [ ] "Używamy tylko niezbędnych cookies (session, CSRF). Brak trackingu" + button "Rozumiem"
  - [ ] Jeśli nigdy nie dodajemy analytics → wystarczy "essential cookies only" notice
- [ ] **Data export endpoint** `/account/export-data/`:
  - [ ] POST → generuje JSON z wszystkimi danymi usera (profile, rezerwacje, audit log entries gdzie user=request.user)
  - [ ] Download jako `dane-osobowe-YYYY-MM-DD.json`
  - [ ] Rate limit: 1× dziennie per user (django-axes)
- [ ] **Right to erasure** (już istnieje `anonymize_employee`, ale rozszerzyć):
  - [ ] `anonymize_employee` ANONIMIZUJE też audit log entries (`user=None`, `object_repr` z imieniem → "[ANONIMIZOWANO]")
  - [ ] Test: po anonymize wyszukanie po imieniu w audit log NIC nie zwraca
- [ ] Link do Privacy Policy w footer każdej strony
- [ ] **Acceptance**: user klika "Pobierz moje dane" → dostaje JSON. Admin klika "Anonimizuj" → wszystko z imieniem znika, audit log entries zostają ale bez PII.

**Effort:** 0.5 dnia.

#### 2.3.E — Custom error pages 404/500/403

- [ ] `templates/errors/404.html` — branded, link "Wróć do dashboardu" + search box
- [ ] `templates/errors/500.html` — branded, "coś poszło nie tak, ekipa została powiadomiona" (informacja, nie kłamstwo)
- [ ] `templates/errors/403.html` — branded, "brak uprawnień" + link do logowania jeśli anonymous
- [ ] `templates/errors/maintenance.html` — gdy aplikacja jest down (placeholder dla przyszłości)
- [ ] `planer_config/urls.py`: `handler404`, `handler500`, `handler403` zdefiniowane
- [ ] **Lokalizacja** wszystkich error pages PL/EN
- [ ] Test: ustawić `DEBUG=False`, wejść na `/nieistnieje/` → custom 404 zamiast django default
- [ ] **Acceptance**: każdy error page wygląda jak część app (header, footer, branding) — nie jak surowy Django default.

**Effort:** 0.3 dnia.

#### 2.3.F — ERD + ADR (Architecture Decision Records)

- [ ] `uv add --dev django-extensions` (jeśli jeszcze nie ma) + `brew install graphviz`
- [ ] `uv run python manage.py graph_models -a -o docs/erd.png --exclude-models=Session,LogEntry,ContentType,Permission,Group`
- [ ] `docs/architecture.md` — Mermaid diagram głównych komponentów (Django apps, PostgreSQL, Chatbot AI z Gemini, Google Maps API, SMTP)
- [ ] `docs/adr/` z 5 krótkimi ADR (1 strona każdy, format MADR):
  - [ ] `001-postgresql-not-sqlite.md` — czemu PostgreSQL od początku
  - [ ] `002-htmx-not-spa.md` — czemu HTMX zamiast React/Vue
  - [ ] `003-pydantic-ai-gemini.md` — czemu Pydantic AI + Gemini dla chatbota
  - [ ] `004-totp-not-webauthn.md` — czemu TOTP zamiast WebAuthn (prostota dla skali)
  - [ ] `005-no-celery-sync-mail.md` — czemu sync mailing zamiast Celery
- [ ] README link do `docs/architecture.md` i `docs/adr/`
- [ ] **Acceptance**: nauczyciel otwiera `docs/erd.png` → widzi schemat bazy 1 spojrzeniem. Otwiera `docs/adr/001-...` → 1 strona "context / decision / consequences".

**Effort:** 0.5 dnia.

#### 2.3.G — Backup strategia + restore fire drill

- [ ] `scripts/backup_db.sh`:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  TIMESTAMP=$(date +%Y-%m-%d_%H%M)
  BACKUP_DIR="${BACKUP_DIR:-./backups}"
  mkdir -p "$BACKUP_DIR"
  PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h localhost -p 5434 -U "$POSTGRES_USER" "$POSTGRES_DB" \
      | gzip > "$BACKUP_DIR/${TIMESTAMP}.sql.gz"
  echo "Backup OK: $BACKUP_DIR/${TIMESTAMP}.sql.gz ($(du -h "$BACKUP_DIR/${TIMESTAMP}.sql.gz" | cut -f1))"
  # Retention: usun starsze niz 30 dni
  find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete
  ```
- [ ] `scripts/restore_db.sh` (do fire drill):
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  BACKUP_FILE="$1"
  TEST_DB="${TEST_DB:-restore_test}"
  createdb -h localhost -p 5434 -U "$POSTGRES_USER" "$TEST_DB"
  gunzip -c "$BACKUP_FILE" | PGPASSWORD="$POSTGRES_PASSWORD" psql -h localhost -p 5434 -U "$POSTGRES_USER" "$TEST_DB"
  # Verify: count records
  PGPASSWORD="$POSTGRES_PASSWORD" psql -h localhost -p 5434 -U "$POSTGRES_USER" -d "$TEST_DB" -c "SELECT COUNT(*) FROM reservations_reservation;"
  dropdb -h localhost -p 5434 -U "$POSTGRES_USER" "$TEST_DB"
  echo "Restore drill OK"
  ```
- [ ] **Fire drill** wykonany: `bash scripts/backup_db.sh && bash scripts/restore_db.sh backups/latest.sql.gz` → count rezerwacji zgadza się z produkcyjnym
- [ ] README "Backup DB" sekcja z cron entry `0 2 * * * cd /app && bash scripts/backup_db.sh`
- [ ] **Acceptance**: skrypt restore na test db pokazuje tę samą liczbę rezerwacji co produkcja → backup jest WIARYGODNY (nie iluzja)

**Effort:** 0.2 dnia.

#### 2.3.H — pytest-bdd Gherkin scenariusze (5)

Wow faktor dla kursu — biznesowe scenariusze zapisane w stylu "Given/When/Then" które każdy klient zrozumie.

- [ ] `tests/bdd/reservations.feature`:
  ```gherkin
  Feature: Cykl zycia rezerwacji
    Scenario: Magazynier rezerwuje maszyne na przyszly tydzien
      Given uzytkownik "seba" jest zalogowany jako Magazynier
      And istnieje maszyna "M-0001" o statusie "W magazynie"
      When seba tworzy rezerwacje na M-0001 od jutra na 5 dni
      Then rezerwacja ma status "oczekujaca"
      And maszyna M-0001 ma status "Zarezerwowana"

    Scenario: Kierownik potwierdza rezerwacje
      Given istnieje rezerwacja "R-100" o statusie "oczekujaca"
      When kierownik klika "Potwierdz" w modal
      Then rezerwacja ma status "potwierdzona"
      And osoba odpowiedzialna otrzymuje mail z potwierdzeniem

    Scenario: Hard Return Policy - maszyna nie wrocila na czas
      Given istnieje rezerwacja konczaca sie wczoraj o statusie "potwierdzona"
      And maszyna jest dalej "Na budowie"
      When uruchamia sie cron daily_sync
      Then rezerwacja ma przedluzony end_date na dzisiaj
      And admin dostaje alert

    Scenario: Konflikt rezerwacji jest wykrywany
      Given istnieje potwierdzona rezerwacja M-0001 od 10-15 czerwca
      When seba probuje stworzyc rezerwacje M-0001 od 12-18 czerwca
      Then dostaje blad "Termin koliduje z inna rezerwacja"

    Scenario: Anulowanie wymaga powodu
      Given istnieje rezerwacja o statusie "potwierdzona"
      When kierownik klika "Anuluj" bez wybierania powodu
      Then formularz pokazuje blad walidacji "Powod jest wymagany"
  ```
- [ ] `tests/bdd/steps_reservations.py` — implementacje step definitions
- [ ] `pytest tests/bdd/ -v` przechodzi
- [ ] **Acceptance**: nauczyciel widzi `.feature` plik → rozumie biznes na pierwszy rzut oka bez czytania kodu.

**Effort:** 0.5 dnia.

#### 2.3.I — Lighthouse audit + Performance

- [ ] Otworzyć `/`, `/rezerwacje/timeline/`, `/maszyny/`, `/mapy/` w Chrome → DevTools → Lighthouse → Audit (mobile + desktop)
- [ ] **Target scores:**
  - [ ] Performance: ≥90
  - [ ] Accessibility: ≥95 (powinno być 100 po 2.3.A)
  - [ ] Best Practices: ≥95
  - [ ] SEO: ≥90
- [ ] **Konkretne fixe** (z Lighthouse recommendations):
  - [ ] Obrazy maszyn → WebP format (już są .webp) + `loading="lazy"` na below-fold
  - [ ] Critical CSS inlined w `<head>` (Tailwind już to robi)
  - [ ] JS bundle splitting (Vite/esbuild jeśli potrzeba — raczej nie, vendored)
  - [ ] HTTP cache headers (Cache-Control na statics, whitenoise to robi)
- [ ] **Acceptance**: 4 strony × 4 score ≥90% → screenshot w `docs/lighthouse-scores.png`

**Effort:** 0.2 dnia.

#### 2.3.J — Dokumentacja użytkownika + README + django check --deploy

- [ ] `docs/instrukcja-magazyniera.pdf` (~5 stron, screenshots z UI): jak zalogować się (z 2FA!), jak zarezerwować maszynę, jak potwierdzić, jak zgłosić awarię
- [ ] `docs/instrukcja-administratora.pdf` (~5 stron): jak dodać użytkownika, jak nadać role, jak zobaczyć audit log, jak wyeksportować raport miesięczny, jak wyłączyć 2FA innego usera
- [ ] **README.md** sekcje:
  - [ ] "Internacjonalizacja" — jak dodać nowy język
  - [ ] "Mailing" — SMTP Google Workspace + App Password
  - [ ] "2FA" — jak skonfigurować pierwszy device, recovery codes
  - [ ] "GDPR" — privacy policy, data export, anonymize
  - [ ] "Production cron" — wszystkie crony
  - [ ] "Backup + restore" — `scripts/backup_db.sh` + `restore_db.sh`
  - [ ] "Architecture" — link do `docs/erd.png` i `docs/adr/`
  - [ ] Badges na top: ![CI] ![Coverage] ![Python] ![Django]
- [ ] **Demo data refresh:**
  - [ ] `uv run python manage.py seed_reservations_topup --until 2026-07-30`
  - [ ] Realne nazwy PL/EN (np. dodać kilku odpowiedzialnych z imionami "Jan Kowalski", "Anna Nowak", "John Smith")
  - [ ] Sprawdzić że ServiceRecord ma `cost` w EUR (po migracji django-money)
- [ ] **`django check --deploy`** clean — zero WARNING:
  - [ ] `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`, `SECURE_HSTS_SECONDS=31536000`, `SECURE_CONTENT_TYPE_NOSNIFF=True`, `X_FRAME_OPTIONS='DENY'`
- [ ] **Performance audit timeline** (Django Debug Toolbar): /rezerwacje/timeline/ z 50+ maszyn × 30 dni → <10 queries, każde <100ms
- [ ] **E2E Playwright** — minimum 3 scenariusze (login + 2FA → dashboard, timeline modal confirm, tworzenie rezerwacji od zera). `make e2e` przechodzi.

**Effort:** 0.5 dnia.

---

### Cały Task 2.3 — Effort total

| Sub-zadanie | Effort | Bezwzględne? |
|---|---|---|
| 2.3.A Accessibility WCAG 2.1 AA | 1 dzień | TAK (EU compliance) |
| 2.3.B CI GitHub Actions | 0.5 dnia | TAK (wow faktor) |
| 2.3.C Security scan (bandit + safety + CSP) | 0.3 dnia | TAK |
| 2.3.D GDPR essentials | 0.5 dnia | TAK (Belgia = EU) |
| 2.3.E Custom error pages | 0.3 dnia | NICE-TO-HAVE |
| 2.3.F ERD + 5 ADR | 0.5 dnia | NICE-TO-HAVE (wow) |
| 2.3.G Backup + restore fire drill | 0.2 dnia | TAK |
| 2.3.H pytest-bdd 5 scenariuszy | 0.5 dnia | NICE-TO-HAVE (wow) |
| 2.3.I Lighthouse audit | 0.2 dnia | NICE-TO-HAVE (wow) |
| 2.3.J Dokumentacja + README + demo + check --deploy + E2E | 0.5 dnia | TAK |
| **TOTAL** | **4.5 dnia** | |

**Bufor pomiędzy końcem Sprint 2 (28.06) a deadline'em (30.06) to tylko 2 dni** — większość 2.3 musi się zacząć już w trakcie Sprint 2 (parallel). Realistycznie:

- 22-24.06: Audit log (Task 2.1, 2 dni równolegle z 2.3.B CI + 2.3.C security)
- 25-27.06: Raporty (Task 2.2, 3 dni równolegle z 2.3.A a11y)
- 28-30.06: pełen polish (2.3.D-J + dokumentacja)

**Jeśli przepełnienie:** P2 (custom errors, ERD/ADR, bdd, lighthouse) idą do bufora lipcowego — wciąż "wow 11/10" jest osiągnięty przez P0 (a11y, CI, security, GDPR, 2FA z S1).

**Acceptance całego M3:** osoba zewnętrzna dostaje link + PDF instrukcji → samodzielnie loguje się (z 2FA), zmienia język na NL, tworzy rezerwację, dostaje mail, eksportuje raport PDF, sprawdza audit log w admin. Wszystko działa. Lighthouse Accessibility = 100%.

---

## Co NIE wchodzi w M3 (świadome cuts — uzasadnienia)

| Cut | Powód |
|-----|-------|
| Hosting (VPS / Fly.io / PythonAnywhere) | Sebastian: "póki co nie hostujemy, wrócimy później". Deployment to potencjalnie 1-2 tyg samego setup'u + monitorowania |
| WebAuthn / Passkeys | 2FA TOTP wystarcza dla skali. WebAuthn dodaje hardware key dependency |
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
git commit -m "feat(M3-S1): i18n pelna lokalizacja PL/EN + flatpickr per-locale"
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

## Definition of Done — cały Milestone 3 (rozszerzony do 11/10 po audycie 01.06.2026)

Przed zakończeniem M3 wszystko poniżej musi być zielone:

**Funkcjonalne:**

- [ ] Wszystkie obszary zakończone: i18n (PL/EN + plurals + EUR), mailing (6 maili × 2 języki + robustness), 2FA TOTP, audit log, raporty Chart.js + PDF, polish
- [ ] Manualny walk-through w przeglądarce po wszystkich widokach × 2 języki = 4 pełne obchody UI
- [ ] 24 maile transakcyjne wysłane manualnie do `info@budmech.pl`, każdy zweryfikowany w Gmail Web (poprawny subject, body, dark mode, unsubscribe link, plaintext fallback)
- [ ] 2FA: login z Google Authenticator działa, recovery codes do downloadu, admin może wyłączyć 2FA innego usera
- [ ] Audit log działa, CSV eksport pobrany i otwarty w Excelu, prune cron usuwa stare
- [ ] Raporty: 4 wykresy renderują się responsively, PDF generuje się z brandingiem
- [ ] GDPR: privacy policy live, data export działa, anonymize obejmuje audit log

**Jakościowe:**

- [ ] `uv run pytest -q -n auto` — 100% pass, coverage ≥ 95%
- [ ] `uv run ruff check . && uv run ruff format --check .` — clean
- [ ] `uv run python manage.py check --deploy` — zero WARNING
- [ ] `uv run bandit -r . -x tests/,migrations/` — zero HIGH severity
- [ ] `uv run safety check` — zero CVE w deps (lub upgrade dokonany)
- [ ] CSP audit: zero violations w DevTools Console
- [ ] **Axe DevTools**: zero violations level AA na 8 kluczowych stronach
- [ ] **Lighthouse**: 4 strony × 4 score (Performance/Accessibility/Best Practices/SEO) — wszystkie ≥90 (Accessibility ≥95)

**Infrastruktura:**

- [ ] **CI GitHub Actions** zielone na każdym push (pytest + ruff + bandit + safety + coverage badge)
- [ ] Coverage badge w README aktualny
- [ ] Backup: `scripts/backup_db.sh` + `restore_db.sh` przetestowane (fire drill OK)
- [ ] E2E Playwright: 3 scenariusze pass (z 2FA flow)
- [ ] pytest-bdd: 5 Gherkin scenariuszy pass

**Dokumentacja:**

- [ ] `docs/instrukcja-magazyniera.pdf` + `docs/instrukcja-administratora.pdf`
- [ ] `docs/erd.png` (Graphviz)
- [ ] `docs/architecture.md` (Mermaid diagram)
- [ ] `docs/adr/001-005-*.md` (5 ADR)
- [ ] `README.md` sekcje: i18n, mailing, 2FA, GDPR, cron, backup, architecture, status badges

**Git:**

- [ ] Wszystko zmergowane do `main` przez `--no-ff` z merge commitami markującymi sprints
- [ ] Zero force-push na `main` / `develop` w trakcie M3

---

## Changelog tego dokumentu

| Data | Event |
|------|-------|
| 2026-06-01 | Utworzony jako konkretny plan zaplecza dla M3 (16 dni roboczych: 15-30.06.2026). Bazuje na audycie agentowym `NOTES_FOR_MILESTONE_3.md` z 2026-04-20, ale ze świadomymi cięciami (zob. sekcja "Co NIE wchodzi w M3") + dostosowaniem decyzji biznesowych: pełne 2 języki PL/EN, mailing przez Google Workspace `info@budmech.pl`, hosting odłożony. |
| 2026-06-01 (v2) | Rozszerzenie planu po audycie adwokata diabła: **dodane 2FA TOTP** (Task 1.3, 1 dzień, OWASP A07:2021), **a11y WCAG 2.1 AA** (European Accessibility Act compliance — wymagane prawem od 28.06.2025), **CI GitHub Actions** (bez deploymentu — sama infrastruktura testowa), **GDPR essentials** (privacy policy, cookie notice, data export, audit log erasure), security scan (bandit + safety + CSP audit), custom error pages, ERD + 5 ADR, backup restore fire drill, pytest-bdd 5 scenariuszy, Lighthouse audit, idempotency cronów mailingu, unsubscribe link, Mailpit w dev. Waluta domyślna EUR (Belgia), dodane `django-money`, `phonenumbers`, `django-otp`, `qrcode`. Plurals (3 formy PL) explicit w DoD. |
