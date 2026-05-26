# language: pl
Właściwość: Cykl życia rezerwacji — anulowanie, edycja, potwierdzenie
  Aby zarządzać rezerwacjami w spójny sposób
  Jako magazynier
  Chcę potwierdzać, anulować i edytować rezerwacje przez serwis

  Scenariusz: Magazynier potwierdza rezerwację OCZEKUJACA
    Mając rezerwację w statusie "OCZEKUJACA"
    Kiedy magazynier potwierdza rezerwację
    Wtedy status rezerwacji to "POTWIERDZONA"

  Scenariusz: Magazynier anuluje rezerwację OCZEKUJACA
    Mając rezerwację w statusie "OCZEKUJACA"
    Kiedy magazynier anuluje rezerwację
    Wtedy status rezerwacji to "ANULOWANA"

  Scenariusz: Magazynier anuluje rezerwację POTWIERDZONA
    Mając rezerwację w statusie "POTWIERDZONA"
    Kiedy magazynier anuluje rezerwację
    Wtedy status rezerwacji to "ANULOWANA"

  Scenariusz: Nielegalne przejście — anulowana nie może być potwierdzona
    Mając rezerwację w statusie "ANULOWANA"
    Kiedy magazynier próbuje potwierdzić rezerwację
    Wtedy operacja kończy się błędem walidacji
    Oraz status rezerwacji to "ANULOWANA"

  Scenariusz: Edycja dat rezerwacji POTWIERDZONA
    Mając rezerwację w statusie "POTWIERDZONA"
    Kiedy magazynier zmienia datę końca rezerwacji na "2026-12-15"
    Wtedy rezerwacja zostaje zapisana z nową datą końca "2026-12-15"
