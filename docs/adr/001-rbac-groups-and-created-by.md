# ADR-001: RBAC oparte o grupy + własność rezerwacji przez `created_by`

- **Status:** Zaakceptowano
- **Data:** 2026-06

## Kontekst

Aplikacja ma trzy role operacyjne (magazynier, kierownik, administrator) oraz
rolę domyślną montażysty (tylko odczyt). Potrzebny jest spójny, odtwarzalny
model uprawnień oraz jednoznaczne przypisanie autora rezerwacji (do powiadomień
e-mail i ograniczenia edycji).

Wcześniej grupy RBAC tworzył wyłącznie ręczny `setup_groups`, więc świeża baza
miała pustą tabelę grup i każdy widok `permission_required` zwracał 403.
Własność rezerwacji rozpoznawano po dopasowaniu free-text pola `person`.

## Decyzja

1. **Grupy RBAC tworzy migracja** (`accounts/0003_create_rbac_groups`) — z jawnym
   utworzeniem uprawnień, tak aby RBAC działał już po pierwszym `migrate` na
   świeżej bazie. `setup_groups` pozostaje jako pomocnik do re-synchronizacji.
2. **Wymuszanie ról opiera się o FUNKCJĘ konta** (`EmployeeProfile.function`),
   mapowaną na grupy Django, a nie o flagę `is_staff`.
3. **Własność rezerwacji to FK `Reservation.created_by`** stemplowane przez
   wszystkie ścieżki tworzenia (formularz, quick-reserve, batch, executor
   chatbota/głosu). Zastępuje dawne dopasowanie po `person`.

## Konsekwencje

- Świeży klon + `migrate` daje działający RBAC bez ręcznych kroków.
- `created_by` jest jednoznacznym adresatem powiadomień (ADR-004) i podstawą
  filtra widoczności w edycji dla nie-administratorów.
- Rezerwacje historyczne/importowane bez `created_by` są widoczne tylko dla
  administratora — akceptowalne, bo dane demonstracyjne tworzone są na nowo.
