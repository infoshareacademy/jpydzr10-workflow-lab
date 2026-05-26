# language: pl
Właściwość: Asystent — zapytanie o stan maszyn
  Aby szybko sprawdzić informacje bez klikania
  Jako magazynier
  Chcę zadać pytanie asystentowi w naturalnym języku

  Scenariusz: Pytanie o liczbę dostępnych maszyn
    Mając zalogowanego pracownika "chatbot_qa_user1"
    Oraz 3 maszyny w stanie "W magazynie"
    Kiedy magazynier pyta asystenta "Ile maszyn jest w magazynie?"
    Wtedy asystent odpowiada zawierając tekst "3"
    Oraz pytanie i odpowiedź są zapisane w historii konwersacji

  Scenariusz: Pytanie bez konfiguracji API zwraca komunikat błędu
    Mając zalogowanego pracownika "chatbot_qa_user2"
    Oraz nieskonfigurowany API klucz Gemini
    Kiedy magazynier pyta asystenta "Sprawdź stan maszyny KOP-001"
    Wtedy asystent odpowiada błędem o brakującym kluczu
