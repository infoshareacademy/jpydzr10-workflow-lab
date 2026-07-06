"""Config sesji Gemini Live dla ConversationRelay — modalność AUDIO + transkrypcja.

🔴 DEMO-KILLER (zweryfikowany realnymi połączeniami): żaden model Gemini Live nie
streamuje TEXT-out — ``response_modalities=['TEXT']`` zwraca błąd API 1007 → na
scenie głucha cisza. Most MUSI używać AUDIO-out + ``output_audio_transcription``
(transkrypt tekstowy → ramki text do ConversationRelay → Twilio robi TTS).
"""

from __future__ import annotations

from chatbot.voice_socket import CONFIRM_TOOL, _build_live_config, _system_instruction


def test_live_config_uses_audio_not_text():
    cfg = _build_live_config(None)
    mods = [getattr(m, "value", m) for m in cfg.response_modalities]
    # Kluczowe: AUDIO, NIE TEXT. Gdyby ktoś przywrócił ['TEXT'] → 1007 → cisza.
    assert mods == ["AUDIO"]


def test_live_config_enables_output_transcription():
    cfg = _build_live_config(None)
    # Bez tego tekst NIE trafia do ConversationRelay (gmsg.text przy AUDIO puste).
    assert cfg.output_audio_transcription is not None


def test_live_config_still_passes_tools():
    cfg = _build_live_config(None)
    # Tool-calling nadal działa (27+ deklaracji przekazanych do modelu).
    assert len(cfg.tools[0].function_declarations) >= 20


def test_system_instruction_is_terse_for_voice():
    # Kanał głosowy: rozmówca słucha → tury muszą być krótkie. Strażnik przeciw
    # powrotowi gadatliwości (recytacja pól akcji = „bla bla czy potwierdzasz").
    instr = _system_instruction(None)
    assert "PRZECZYTAJ podgląd" not in instr  # usunięte źródło rozwlekłości
    assert "1-2" in instr  # twardy limit długości tury
    assert "zwięzły" in instr.lower()
    assert "potwierdzasz?" in instr  # zwięzły format potwierdzenia zamiast wyliczania pól


def test_system_instruction_keeps_confirm_contract():
    # Zwięzłość NIE może zdjąć kontraktu bezpieczeństwa: write → potwierdzenie → confirm.
    assert CONFIRM_TOOL in _system_instruction(None)
