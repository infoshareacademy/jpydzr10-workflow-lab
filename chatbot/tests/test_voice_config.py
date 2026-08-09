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
    assert "krótk" in instr.lower()  # limit długości tury
    assert "JEDNO pytanie naraz" in instr  # rozmowa krok po kroku, nie kwestionariusz
    assert "potwierdzasz?" in instr  # zwięzły format potwierdzenia zamiast wyliczania pól


def test_system_instruction_keeps_confirm_contract():
    # Zwięzłość NIE może zdjąć kontraktu bezpieczeństwa: write → potwierdzenie → confirm.
    assert CONFIRM_TOOL in _system_instruction(None)


def test_system_instruction_pins_machine_name_pronunciation():
    """Nazwa maszyny ma być czytana dosłownie, nie zamieniana na liczebnik porządkowy.

    Rozmówca słyszał raz „minikoparka dwa", raz „druga minikoparka" — dla ucha to dwie
    różne maszyny, a w systemie jedna. Instrukcja musi to rozstrzygać wprost.
    """
    instr = _system_instruction(None)
    assert "druga minikoparka" in instr, "brak zakazu formy porządkowej"
    assert "minikoparka dwa" in instr, "brak wzorca poprawnej wymowy"


def test_system_instruction_speaks_as_a_woman():
    """Lektor jest damski, więc asystentka mówi o sobie w rodzaju żeńskim."""
    instr = _system_instruction(None)
    assert "sprawdziłam" in instr
    assert "KOBIETĄ" in instr


def test_system_instruction_mirrors_casual_greeting():
    """Na zagajenie »cześć wariatko« odpowiada tym samym tonem — raz, nie w kółko."""
    instr = _system_instruction(None)
    assert "wariacie" in instr or "wariatko" in instr, "brak reguły dopasowania tonu"
    assert "RAZ" in instr, "brak ograniczenia, żeby nie powtarzać zwrotu w kółko"


def test_system_instruction_reuses_data_for_next_machine():
    """Kolejna maszyna »na tych samych warunkach« = przepisanie danych, bez dopytywania."""
    instr = _system_instruction(None)
    assert "KOLEJNA MASZYNA" in instr
    assert "PRZEPISZ" in instr


def test_rule_numbering_has_no_duplicates():
    """Numeracja reguł musi być ciągła — duplikat myli model przy odwołaniach."""
    import re

    numbers = [int(m) for m in re.findall(r"^(\d+)\.", _system_instruction(None), re.MULTILINE)]
    assert numbers == sorted(set(numbers)), f"numeracja reguł się dubluje: {numbers}"
    assert numbers == list(range(1, len(numbers) + 1)), f"numeracja nieciągła: {numbers}"
