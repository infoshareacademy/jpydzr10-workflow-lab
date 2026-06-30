# ADR-003: Wymuszanie 2FA (TOTP) dla kont uprzywilejowanych

- **Status:** Zaakceptowano
- **Data:** 2026-06

## Kontekst

Konta z podwyższonymi uprawnieniami (administrator, kierownik, magazynier) mają
dostęp do operacji modyfikujących dane floty i rezerwacji. Samo hasło to za mało
— potrzebny jest drugi składnik uwierzytelniania.

## Decyzja

Wdrożono **TOTP** (zgodny z Google Authenticator) przez `django-otp`:

- **Predykat wymogu jest FUNKCYJNY** — `is_totp_required_for_user` zwraca prawdę
  dla superusera oraz funkcji `ADMIN`/`KIEROWNIK`/`MAGAZYNIER`. Montażysta
  (tylko odczyt) jest zwolniony. Świadomie NIE opieramy się o `is_staff`.
- **Wymuszanie przez middleware** (`TwoFactorEnforcementMiddleware`), które
  przekierowuje uprawnionych, niezweryfikowanych użytkowników do setupu/weryfikacji.
  Flaga `OTP_ENFORCE_2FA` (env) pozwala wyłączyć wymuszanie w dev.
- **Obejście testowe** (`OTP_TESTING_BYPASS`) jest czytane W CZASIE ŻĄDANIA, więc
  `@override_settings` działa w testach, a istniejące testy (logujące przez
  `force_login`) pozostają zielone bez modyfikacji.
- Setup: kod QR (data-URI, działa pod CSP `img-src 'data:'`) + ręczny sekret +
  **10 jednorazowych kodów zapasowych** (StaticToken) z pobraniem TXT.

## Konsekwencje

- Uprawnione konta muszą przejść TOTP zanim uzyskają dostęp do reszty aplikacji.
- Lista wyjątków (login/logout/setup 2FA/statyki/healthz/`/debug/boom/`) zapobiega
  pętli przekierowań.
- Sekrety TOTP kont demonstracyjnych i kody zapasowe administratora są poza
  repozytorium (lokalny plik reguł).
