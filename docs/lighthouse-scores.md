# Wyniki Lighthouse — dostępność i jakość

Audyt wykonany lokalnie (Chrome Lighthouse, tryb desktop, navigation) na uruchomionej
aplikacji (zalogowany użytkownik) z **wyłączonym django-debug-toolbar** (`DJDT_DISABLED=1`,
zob. `planer_config/settings/dev.py`) — toolbar to narzędzie deweloperskie nieobecne w
produkcji, więc audyt bez niego odzwierciedla realny stan aplikacji. Wartości w skali 0–100.

| Strona | Accessibility | Best Practices | SEO |
|--------|:---:|:---:|:---:|
| Dashboard (`/`) | **100** | 100 | 100 |
| Lista maszyn (`/maszyny/`) | **100** | 100 | 100 |
| Lista rezerwacji (`/rezerwacje/`) | **100** | 100 | 100 |
| Raporty serwisowe (`/serwis/raporty/`) | **100** | 100 | 100 |

> Pozostałe widoki dziedziczą ten sam szablon bazowy (`base.html`), nawigację i arkusz
> stylów, więc powyższe są reprezentatywne dla całej aplikacji.

## Cel projektu (DoD)

- Accessibility **≥ 95** — **osiągnięte z zapasem** (100 na wszystkich badanych stronach).
- Best Practices ≥ 95 — osiągnięte (100).
- SEO ≥ 90 — osiągnięte (100).

## Poprawki dostępności wprowadzone na podstawie audytu

- Pole wyszukiwania (`#topbar-search`) otrzymało `role="combobox"`, dzięki czemu
  atrybuty `aria-autocomplete` / `aria-controls` / `aria-expanded` są zgodne z rolą
  (naprawa `aria-allowed-attr`).
- Kropki statusu przeglądu na liście maszyn (×43) dostały `role="img"` — `aria-label`
  jest teraz dozwolony na tych elementach (naprawa `aria-prohibited-attr`).
- Usunięto rozbieżne `aria-label` z kart KPI/skrótów dashboardu i linków „Dziś w trasie";
  nazwa dostępna wynika z widocznego tekstu (naprawa `label-content-name-mismatch`).
- Stopka (copyright) podbita `text-slate-400`→`text-slate-500` dla kontrastu AA.

### Domknięcie do 100/100 (audyt 2026-06-30, toolbar wyłączony)

- **Kontrast (`color-contrast`)**: drugorzędny tekst z odwróconą parą
  `text-slate-400 dark:text-slate-500` (skeleton modalu przeglądów na dashboardzie,
  podpis typu maszyny i licznik „widocznych:" na liście maszyn, liczniki paginacji
  rezerwacji/budów) przełączony na standardową, zgodną z AA parę
  `text-slate-500 dark:text-slate-400`. Dekoracyjne ikony SVG (`aria-hidden`) celowo
  nietknięte — nie podlegają regule kontrastu tekstu.
- **`label-content-name-mismatch`**: przyciski przełącznika widoku listy maszyn miały
  `aria-label="Widok tabeli/kafelków"` rozbieżne z widocznym „Tabela/Kafelki" →
  `aria-label` zrównane z widocznym tekstem (na mobile, gdy tekst ukryty, nadal etykietuje).
- **`label` + `tabindex`**: filtr dat wykresu kosztów na stronie raportów używał
  `flatpickr` z `altInput`, którego dynamicznie tworzony widoczny klon gubił powiązanie
  z `<label>` i dziedziczył `tabindex` > 0. Te dwa pola pozostawiono jako natywne
  `<input type="date">` (`data-skip-flatpickr`) — natywny date-picker jest w pełni
  dostępny (etykieta `for`/`id`, brak dodatniego `tabindex`), a wartość nadal trafia do
  backendu w formacie `Y-m-d`. Dla pozostałych pól dat (formularze) `flatpickr` zachowuje
  europejski format dd.mm.yyyy, a `onReady` kopiuje etykietę na `aria-label` klonu i
  czyści dodatni `tabindex` (`static/js/app.js`).

## Uwagi

Markup spełnia WCAG 2.1 AA na poziomie struktury: skip-link, `prefers-reduced-motion`,
pierścienie focus-visible, etykiety pól formularzy, role ARIA, cele dotykowe 44 px,
`lang` na `<html>`. Testy regresji: `tests/test_a11y.py`.

> Kategoria „Agentic Browsing" w nowszym Lighthouse nie należy do WCAG/dostępności i nie
> jest celem projektu (dotyczy maszynowej nawigacji po stronie).
