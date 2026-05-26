# language: pl
Właściwość: Wykrywanie konfliktów rezerwacji
  Jako system planowania rezerwacji
  Chcę odrzucać próby tworzenia kolidujących rezerwacji
  Aby uniknąć podwójnego rezerwowania tej samej maszyny

  Scenariusz: Zakładka termin nakładających się rezerwacji rzuca ValidationError
    Mając maszynę o UID "M-2001" ze statusem "W magazynie"
    Oraz istniejącą rezerwację maszyny "M-2001" od "2026-07-10" do "2026-07-15" ze statusem "potwierdzona"
    Kiedy próbuję utworzyć rezerwację maszyny "M-2001" od "2026-07-12" do "2026-07-18"
    Wtedy próba kończy się błędem ValidationError zawierającym "kolidujących"

  Scenariusz: Stykające się daty traktowane są jako konflikt
    Mając maszynę o UID "M-2002" ze statusem "W magazynie"
    Oraz istniejącą rezerwację maszyny "M-2002" od "2026-08-01" do "2026-08-05" ze statusem "potwierdzona"
    Kiedy próbuję utworzyć rezerwację maszyny "M-2002" od "2026-08-05" do "2026-08-10"
    Wtedy próba kończy się błędem ValidationError zawierającym "kolidujących"

  Scenariusz: Anulowana rezerwacja nie generuje konfliktu
    Mając maszynę o UID "M-2003" ze statusem "W magazynie"
    Oraz istniejącą rezerwację maszyny "M-2003" od "2026-09-01" do "2026-09-10" ze statusem "anulowana"
    Kiedy magazynier tworzy nową rezerwację maszyny "M-2003" od "2026-09-05" do "2026-09-08" dla osoby "Piotr Wiśniewski"
    Wtedy rezerwacja jest poprawnie utworzona
    Oraz w bazie są dokładnie 2 rezerwacje
