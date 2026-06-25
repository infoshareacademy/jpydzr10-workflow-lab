# ADR-007: Identyfikacja dzwoniącego w agencie głosowym (caller-ID)

- **Status:** Zaakceptowano (z akceptacją ryzyka na czas pokazu)
- **Data:** 2026-06

## Kontekst

Agent głosowy rozpoznaje rozmówcę po numerze dzwoniącego (`From`) i mapuje go na
konto pracownika (`accounts.services.user_for_phone`). Na tej podstawie nadaje
zakres uprawnień: administrator może wykonywać akcje zapisujące, montażysta i
nieznany numer (gość) — tylko odczyt.

Caller-ID jest jednak **słabym, możliwym do podrobienia** czynnikiem (spoofing
numeru). Pozostaje to w napięciu z wymogiem 2FA dla kont uprzywilejowanych
(ADR-003), którego kanał głosowy nie egzekwuje tak jak interfejs web.

## Decyzja

- Caller-ID służy wyłącznie do **wstępnego przypisania tożsamości**; **realnym
  zabezpieczeniem pozostaje sprawdzanie uprawnień** w warstwie narzędzi
  (`_check_user_can` / `has_perm`) — to samo, co w czacie. Numer nieznany lub
  niejednoznaczny → gość (tylko odczyt), nigdy uprzywilejowany domyślnie.
- Każda akcja **zapisująca wymaga głosowego potwierdzenia** (propozycja →
  „tak”), a wykonanie i tak ponownie weryfikuje uprawnienia.
- Na czas pokazu **ryzyko spoofingu jest akceptowane** (kontrolowane środowisko).
  Opcjonalnym wzmocnieniem jest PIN (głosowy/DTMF) przed akcjami zapisującymi
  administratora — do włączenia wg decyzji autora.

## Konsekwencje

- Bezpieczeństwo nie opiera się na samym numerze — nawet przy podrobionym
  caller-ID użytkownik bez uprawnień nie wykona akcji zapisującej.
- Tożsamość przekazywana do warstwy WS jest podpisana (krótkotrwały nonce),
  co utrudnia jej podmianę między webhookiem a gniazdem.
- Poza pokazem rekomendowane jest wzmocnienie (PIN/DTMF) lub rezygnacja z akcji
  zapisujących przez kanał głosowy dla kont uprzywilejowanych.
