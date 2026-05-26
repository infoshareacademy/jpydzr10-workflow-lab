# language: pl
Właściwość: Status przeglądu technicznego maszyny
  Jako magazynier
  Chcę widzieć przy każdej maszynie kolorowy badge statusu przeglądu
  Aby wiedzieć kiedy zaplanować wizytę serwisanta

  Scenariusz: Maszyna z przeglądem w odległej przyszłości ma status "ok"
    Mając zamrożoną datę "2026-06-15"
    Oraz maszynę o UID "M-3001" z datą przeglądu "2026-12-01"
    Kiedy odczytuję status przeglądu maszyny "M-3001"
    Wtedy status przeglądu maszyny wynosi "ok"

  Scenariusz: Maszyna z przeglądem w ciągu 14 dni ma status "warning"
    Mając zamrożoną datę "2026-06-15"
    Oraz maszynę o UID "M-3002" z datą przeglądu "2026-06-20"
    Kiedy odczytuję status przeglądu maszyny "M-3002"
    Wtedy status przeglądu maszyny wynosi "warning"

  Scenariusz: Maszyna z przeterminowanym przeglądem ma status "overdue"
    Mając zamrożoną datę "2026-06-15"
    Oraz maszynę o UID "M-3003" z datą przeglądu "2026-05-01"
    Kiedy odczytuję status przeglądu maszyny "M-3003"
    Wtedy status przeglądu maszyny wynosi "overdue"
