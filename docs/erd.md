# Diagram ERD — model danych

Diagram encji i relacji głównych modeli domenowych aplikacji. Renderuje się
bezpośrednio na GitHub (Mermaid).

```mermaid
erDiagram
    USER ||--|| EMPLOYEE_PROFILE : "ma profil"
    USER ||--o{ RESERVATION : "utworzył (created_by)"
    USER ||--o{ CONVERSATION : "prowadzi"
    USER ||--o{ AUDIT_LOG_ENTRY : "wykonał akcję"

    EMPLOYEE_PROFILE {
        string function "magazynier|montażysta|kierownik|admin"
        string phone "E.164, unikalny"
        string preferred_language "pl|en (domyślny język UI)"
        bool is_active_employee
        bool is_anonymized "GDPR Art.17"
    }

    MACHINE ||--o{ RESERVATION : "jest rezerwowana"
    MACHINE ||--o{ SERVICE_RECORD : "ma wpisy serwisowe"
    MACHINE {
        string uid "np. KOP-001, unikalny"
        string machine_type
        string status "W magazynie|Na budowie|..."
        date inspection_date "termin przeglądu"
        datetime inspection_warning_sent_at "idempotency alertu przeglądu"
    }

    CONSTRUCTION_SITE ||--o{ RESERVATION : "obejmuje"
    CONSTRUCTION_SITE {
        string project_number "BUD-RRRR-NNN"
        string status "aktywna|zakończona"
    }

    RESERVATION {
        date start_date
        date end_date
        string person
        string status "oczekująca|potwierdzona|anulowana|zakończona"
        uuid batch_id "grupa rezerwacji"
        datetime confirmation_email_sent_at
        datetime reminder_sent_at "idempotency przypomnienia T-1"
    }

    SERVICE_RECORD {
        string record_type "przegląd_*|naprawa"
        money cost "kwota + waluta (EUR/PLN)"
        date performed_date
        date next_inspection
    }

    CONVERSATION ||--o{ MESSAGE : "zawiera"
    CONVERSATION {
        string title
        json pending_action "stan propozycja→potwierdzenie (czat)"
    }
    MESSAGE {
        string role "user|assistant"
        text content
    }

    AUDIT_LOG_ENTRY {
        string action "nazwa widoku, np. reservations:confirm"
        string object_type "etykieta modelu, np. reservations.Reservation"
        string object_id
        json changes "diff pól (pre/post)"
        ip_address ip "X-Forwarded-For"
        datetime timestamp
    }
```

## Kluczowe relacje i decyzje

- **`Reservation.created_by → User`** — autor rezerwacji (adresat e-maila
  potwierdzającego, podstawa widoczności w edycji). Patrz ADR-001.
- **`ServiceRecord.cost`** to `MoneyField` (kwota + waluta). Patrz ADR-002.
- **`EmployeeProfile.function`** napędza grupy RBAC (migracja
  `accounts.0003_create_rbac_groups`) oraz wymóg 2FA. Patrz ADR-001, ADR-003.
- **Klucze obce** maszyn i budów są `PROTECT` — rekord nadrzędny nie znika, gdy
  istnieją powiązane rezerwacje/wpisy serwisowe.
- **Audyt — dwie warstwy:** `django-simple-history` trzyma pełną historię PÓL
  każdego modelu (tabele historyczne, pominięte na diagramie), a
  `AuditLogEntry` rejestruje AKCJE użytkownika (które żądanie POST/PUT/PATCH/
  DELETE, kto, IP, na czym) — także zdarzenia bez zmiany modelu (logowanie,
  eksport). Patrz ADR-008.
