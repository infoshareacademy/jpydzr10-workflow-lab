# ADR-006: Samodzielnie hostowany GlitchTip do obserwowalności błędów

- **Status:** Zaakceptowano
- **Data:** 2026-06

## Kontekst

Aplikacja potrzebuje centralnego zbierania i grupowania nieobsłużonych wyjątków
(błędów produkcyjnych) zamiast polegania wyłącznie na logach serwera. Logi są
rozproszone, trudne do przeszukania i nie grupują powtarzających się błędów ani
nie pokazują częstotliwości występowania.

Rozważane opcje:

1. **Sentry (SaaS)** — dojrzała usługa, ale dane błędów (w tym potencjalnie
   fragmenty danych użytkowników) trafiają do zewnętrznego dostawcy, a koszt
   rośnie z liczbą zdarzeń.
2. **GlitchTip (self-hosted)** — open-source, w pełni kompatybilny z Sentry SDK,
   uruchamiany we własnej infrastrukturze.
3. **Tylko logi + alerty na plikach** — najtańsze, ale bez grupowania i bez
   wygodnego przeglądu.

## Decyzja

Wybrano **samodzielnie hostowany GlitchTip**, integrowany przez oficjalny
`sentry-sdk` (GlitchTip celowo utrzymuje zgodność protokołu z Sentry).

Powody:

- **Rezydencja danych** — zdarzenia błędów pozostają we własnej infrastrukturze;
  brak wysyłania danych do zewnętrznego dostawcy.
- **Zerowy koszt za zdarzenie** — brak opłat zależnych od wolumenu błędów.
- **Kompatybilność** — wykorzystanie standardowego `sentry-sdk`, więc integracja
  w Django jest minimalna i wymienna na Sentry bez zmian w kodzie aplikacji.

## Konsekwencje

- Integracja jest **opcjonalna i sterowana zmienną `SENTRY_DSN`**. Bez DSN SDK
  nie jest inicjalizowany — aplikacja nie wysyła żadnych zdarzeń i nie ma
  zależności runtime od usługi obserwowalności (`planer_config/settings/base.py`).
- Funkcja `before_send` **wycina wrażliwe pola** (hasła, tokeny, sekrety, CSRF,
  nagłówki autoryzacji) z payloadu, a `send_default_pii=False` ogranicza dane
  osobowe.
- GlitchTip działa jako **osobny projekt compose** (`docker-compose.glitchtip.yml`,
  projekt `glitchtip-obs`) z własną bazą PostgreSQL (trwały, nazwany wolumen) i
  Valkey. Nie koliduje z bazą aplikacji ani z portami innych usług (web: 9000).
- Obrazy kontenerów są przypięte po digeście / wersji starszej niż 14 dni,
  zgodnie z polityką bezpieczeństwa łańcucha dostaw.
- Endpoint `/debug/boom/` (tylko superuser) służy jednorazowej weryfikacji, że
  nieobsłużone wyjątki trafiają do zgrupowanych zgłoszeń.

## Trzy warstwy obserwowalności

1. **Logowanie strukturalne** (`LOGGING` w `base.py`) — bieżący wgląd w działanie.
2. **django-simple-history** — audyt zmian danych (kto/co/kiedy).
3. **GlitchTip** — grupowanie i przegląd nieobsłużonych wyjątków.
