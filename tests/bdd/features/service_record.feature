# language: pl
Właściwość: Wpisy serwisowe i automatyczna aktualizacja przeglądu
  Jako serwisant
  Chcę zarejestrować wpis serwisowy (przegląd lub naprawę)
  Aby data następnego obowiązkowego przeglądu maszyny była aktualna

  Scenariusz: Przegląd kwartalny aktualizuje datę następnego przeglądu maszyny o 3 miesiące
    Mając maszynę o UID "M-4001" z datą przeglądu "2026-01-01"
    Kiedy serwisant rejestruje wpis "przegląd_kwartalny" dla maszyny "M-4001" z datą wykonania "2026-06-15"
    Wtedy maszyna "M-4001" ma datę przeglądu ustawioną na "2026-09-15"

  Scenariusz: Naprawa nie aktualizuje daty przeglądu maszyny
    Mając maszynę o UID "M-4002" z datą przeglądu "2026-01-01"
    Kiedy serwisant rejestruje wpis "naprawa" dla maszyny "M-4002" z datą wykonania "2026-06-15"
    Wtedy maszyna "M-4002" ma datę przeglądu ustawioną na "2026-01-01"

  Scenariusz: Data wykonania w przyszłości rzuca ValidationError
    Mając zamrożoną datę "2026-06-15"
    Oraz maszynę o UID "M-4003" z datą przeglądu "2026-01-01"
    Kiedy serwisant próbuje zarejestrować wpis "przegląd_kwartalny" dla maszyny "M-4003" z datą wykonania "2026-12-31"
    Wtedy próba kończy się błędem ValidationError zawierającym "przyszłości"
