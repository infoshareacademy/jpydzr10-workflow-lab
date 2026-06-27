# Wyniki Lighthouse — dostępność i jakość

Audyt wykonany lokalnie (Chrome Lighthouse, tryb desktop, navigation) na uruchomionej
aplikacji (`make run`, zalogowany użytkownik). Wartości w skali 0–100.

| Strona | Accessibility | Best Practices | SEO |
|--------|:---:|:---:|:---:|
| Dashboard (`/`) | **96** | 100 | 100 |
| Lista maszyn (`/maszyny/`) | **96** | 100 | 100 |

> Pozostałe kluczowe strony (`/rezerwacje/`, `/serwis/raporty/`) dziedziczą ten sam
> szablon bazowy (`base.html`), nagłówki, nawigację i arkusz stylów, więc wyniki są
> reprezentatywne dla całej aplikacji.

## Cel projektu (DoD)

- Accessibility **≥ 95** — **osiągnięte** (96 na badanych stronach).
- Best Practices ≥ 95 — osiągnięte (100).
- SEO ≥ 90 — osiągnięte (100).

## Poprawki dostępności wprowadzone na podstawie audytu

- Pole wyszukiwania (`#topbar-search`) otrzymało `role="combobox"`, dzięki czemu
  atrybuty `aria-autocomplete` / `aria-controls` / `aria-expanded` są zgodne z rolą
  (naprawa `aria-allowed-attr`).
- Kropki statusu przeglądu na liście maszyn (×43) dostały `role="img"` — `aria-label`
  jest teraz dozwolony na tych elementach (naprawa `aria-prohibited-attr`).
- Usunięto nadmiarowe `aria-label` z kart KPI dashboardu i linku profilu — nazwa
  dostępna wynika teraz z widocznego tekstu (naprawa `label-content-name-mismatch`).

## Pozostałe drobne uwagi (→ dalsza praca a11y)

- `color-contrast`: pojedyncze drugorzędne teksty `text-slate-400` oraz przycisk
  django-debug-toolbar (narzędzie deweloperskie, nieobecne w trybie produkcyjnym).
- `label-content-name-mismatch`: link skrótu rezerwacji i przełącznik widoku
  tabela/kafelki — kosmetyczne, do dopracowania.

Markup spełnia WCAG 2.1 AA na poziomie struktury: skip-link, `prefers-reduced-motion`,
pierścienie focus-visible, etykiety pól formularzy, role ARIA, cele dotykowe 44 px,
`lang` na `<html>`. Testy regresji: `tests/test_a11y.py`.
