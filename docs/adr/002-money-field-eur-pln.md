# ADR-002: Koszt serwisu jako MoneyField (EUR domyślnie, PLN historycznie)

- **Status:** Zaakceptowano
- **Data:** 2026-06

## Kontekst

Koszt wpisu serwisowego był zwykłym `DecimalField` z walutą zaszytą w etykiecie
("Koszt (PLN)"). Operacje prowadzone są w euro, ale dane historyczne (Milestone 1)
pochodzą z rozliczeń w złotówkach. Potrzebna jest jawna, przechowywana waluta.

## Decyzja

Pole `ServiceRecord.cost` to **`MoneyField` (django-money)** — przechowuje kwotę
i walutę. Domyślna waluta to **EUR**; dozwolone waluty: `("EUR", "PLN")`.

Migracja danych ustawia **PLN** na rekordach sprzed `2026-06-01` (dane
historyczne), nowe rekordy domyślnie EUR. Formularz pozostaje pojedynczym polem
kwoty (waluta domyślna EUR), aby nie komplikować UI.

## Konsekwencje

- Kwoty mają jednoznaczną walutę; raporty i eksport pokazują kwotę + walutę.
- Agregacja kosztów (`Sum`) operuje na kwocie; przy mieszanych walutach
  prezentujemy wartości per rekord z ich walutą (bez automatycznego przeliczania
  kursu — poza zakresem).
- Dodano zależność `django-money` (+ `py-moneyed`, `Babel`) zgodnie z polityką
  wersji (wydania starsze niż 14 dni).
