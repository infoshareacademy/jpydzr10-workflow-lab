"""Config sesji Gemini Live dla ConversationRelay — modalność AUDIO + transkrypcja.

🔴 DEMO-KILLER (zweryfikowany realnymi połączeniami): żaden model Gemini Live nie
streamuje TEXT-out — ``response_modalities=['TEXT']`` zwraca błąd API 1007 → na
scenie głucha cisza. Most MUSI używać AUDIO-out + ``output_audio_transcription``
(transkrypt tekstowy → ramki text do ConversationRelay → Twilio robi TTS).
"""

from __future__ import annotations

from chatbot.voice_socket import _build_live_config


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
