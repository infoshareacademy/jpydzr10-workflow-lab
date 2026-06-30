# ADR-008: Dziennik zdarzeń jako osobna warstwa AKCJI nad simple-history

- **Status:** Zaakceptowano
- **Data:** 2026-06

## Kontekst

Wymóg „logowania zdarzeń / audit log" zakłada możliwość odpowiedzi na pytanie
*kto, kiedy i z jakiego adresu wykonał daną akcję* — także akcję, która nie
zmienia żadnego modelu (logowanie, eksport danych, nieudana próba zapisu).

W projekcie działał już `django-simple-history`, który snapshotuje pełną
historię PÓL każdego śledzonego modelu (`Machine`, `Reservation`,
`ServiceRecord`, `EmployeeProfile`). To dobrze odpowiada na pytanie *co się
zmieniło w rekordzie*, ale **nie** rejestruje zdarzeń bez zmiany modelu ani
kontekstu żądania (adres IP, klient, nazwa wywołanej trasy).

## Decyzja

Wprowadzono **drugą, komplementarną warstwę** zamiast rozbudowy simple-history:

1. **`core.AuditLogEntry`** — jeden wpis na udane (2xx/3xx) żądanie mutujące
   (POST/PUT/PATCH/DELETE): `user`, `action` (nazwa widoku, np.
   `reservations:confirm`), `object_type/id/repr`, `changes` (diff pól), `ip_address`,
   `user_agent`, `timestamp`.
2. **`core.middleware.AuditLogMiddleware`** otwiera kontekst audytu na czas
   żądania; sygnały `pre_save`/`post_save`/`post_delete` na śledzonych modelach
   liczą diff pól, a middleware materializuje wpisy po odpowiedzi. Zapis audytu
   jest fail-soft (nigdy nie wywraca żądania użytkownika).
3. **Retencja** komendą `prune_audit_log --older-than 90`; admin read-only z
   filtrami i eksportem CSV (UTF-8 BOM).

`simple-history` **zostaje** — obie warstwy odpowiadają na różne pytania:
simple-history na *„jak zmieniał się ten rekord w czasie"*, AuditLogEntry na
*„jakie akcje wykonywali użytkownicy i z jakiego kontekstu"*.

## Konsekwencje

- Pełna rozliczalność akcji, w tym zdarzeń nie-modelowych (logowanie, eksport).
- Niewielki narzut: dodatkowy odczyt stanu sprzed zapisu tylko w obrębie żądania
  audytowanego (poza nim sygnały krótko-spinają na `is_active()`).
- Operacje masowe (`bulk_create`, `queryset.update/delete`) nie emitują sygnałów
  per-instancja, więc nie trafiają do dziennika — świadome ograniczenie (akcje
  UI idą przez `instance.save()`).
- Anonimizacja RODO (Art.17) wymazuje dane osobowe (IP, User-Agent) we wpisach
  zanonimizowanego użytkownika; sam fakt akcji zostaje dla rozliczalności.
