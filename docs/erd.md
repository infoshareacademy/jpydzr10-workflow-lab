# Diagram ERD — model danych

Diagram encji i relacji głównych modeli domenowych aplikacji. Renderuje się
bezpośrednio na GitHub (Mermaid).

```mermaid
erDiagram
    USER ||--|| EMPLOYEE_PROFILE : "ma profil"
    USER ||--o{ RESERVATION : "utworzył (created_by)"
    USER ||--o{ CONVERSATION : "prowadzi"

    EMPLOYEE_PROFILE {
        string function "magazynier|montażysta|kierownik|admin"
        string phone "E.164, unikalny"
        bool is_active_employee
        bool is_anonymized "GDPR Art.17"
    }

    MACHINE ||--o{ RESERVATION : "jest rezerwowana"
    MACHINE ||--o{ SERVICE_RECORD : "ma wpisy serwisowe"
    MACHINE {
        string uid "np. KOP-001, unikalny"
        string machine_type
        string status "W magazynie|Na budowie|..."
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
```

## Kluczowe relacje i decyzje

- **`Reservation.created_by → User`** — autor rezerwacji (adresat e-maila
  potwierdzającego, podstawa widoczności w edycji). Patrz ADR-001.
- **`ServiceRecord.cost`** to `MoneyField` (kwota + waluta). Patrz ADR-002.
- **`EmployeeProfile.function`** napędza grupy RBAC (migracja
  `accounts.0003_create_rbac_groups`) oraz wymóg 2FA. Patrz ADR-001, ADR-003.
- **Klucze obce** maszyn i budów są `PROTECT` — rekord nadrzędny nie znika, gdy
  istnieją powiązane rezerwacje/wpisy serwisowe.
- **Audyt** zmian każdego modelu zapewnia `django-simple-history` (tabele
  historyczne, pominięte na diagramie dla czytelności).
