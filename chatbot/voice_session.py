"""Stan pojedynczej rozmowy głosowej — czysta, testowalna maszyna stanów.

Trzymany w pamięci procesu agenta głosowego (jeden obiekt na połączenie). NIE
zapisujemy stanu oczekującej akcji do ``Conversation.pending_action`` — tam żyje
stan czatu tekstowego; głos ma własny, ulotny stan. Do audytu trafia wyłącznie
zapis ``Message`` (poza tą klasą).

Przepływ: ``IDLE`` → (propozycja zapisu) ``AWAITING_CONFIRMATION`` →
(potwierdzenie) wykonanie i powrót do ``IDLE`` albo (anulowanie) ``IDLE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class VoiceState(StrEnum):
    IDLE = "idle"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


@dataclass
class VoiceCallSession:
    """Ulotny stan jednej rozmowy głosowej.

    ``user`` jest rozpoznawany po numerze dzwoniącego (caller-ID). ``None``
    oznacza gościa (tylko odczyt — żadnych akcji zapisujących).
    """

    call_sid: str
    user: Any = None  # Django User albo None (gość)
    state: VoiceState = VoiceState.IDLE
    pending_action: str | None = None
    pending_params: dict[str, Any] = field(default_factory=dict)
    transcript: list[dict[str, str]] = field(default_factory=list)

    # --- własności identyfikacji ---
    @property
    def is_guest(self) -> bool:
        return self.user is None

    @property
    def can_write(self) -> bool:
        """Gość nie może wykonywać akcji zapisujących (read-only z konstrukcji)."""
        return self.user is not None

    # --- maszyna stanów propozycja → potwierdzenie ---
    def propose(self, action: str, params: dict[str, Any]) -> None:
        """Zapamiętuje akcję oczekującą na głosowe potwierdzenie."""
        self.pending_action = action
        self.pending_params = dict(params)
        self.state = VoiceState.AWAITING_CONFIRMATION

    def has_pending(self) -> bool:
        # Równość (nie tożsamość) — odporne na ustawienie stanu zwykłym stringiem
        # (StrEnum porównuje się wartością) zamiast instancją enuma.
        return self.state == VoiceState.AWAITING_CONFIRMATION and self.pending_action is not None

    def confirm(self) -> tuple[str, dict[str, Any]]:
        """Zwraca oczekującą akcję i czyści stan (przejście do IDLE).

        Raises:
            ValueError: gdy nie ma akcji oczekującej (błąd logiki wołania).
        """
        if not self.has_pending():
            raise ValueError("Brak akcji oczekującej na potwierdzenie.")
        action, params = self.pending_action, self.pending_params
        self._reset()
        return action, params  # type: ignore[return-value]

    def cancel(self) -> None:
        """Porzuca oczekującą akcję bez wykonania."""
        self._reset()

    def _reset(self) -> None:
        self.pending_action = None
        self.pending_params = {}
        self.state = VoiceState.IDLE

    def add_turn(self, role: str, text: str) -> None:
        """Dokłada wpis do transkryptu (do audytu / kontekstu)."""
        self.transcript.append({"role": role, "text": text})
