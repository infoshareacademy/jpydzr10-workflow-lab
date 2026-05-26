# language: pl
Właściwość: Tworzenie rezerwacji maszyny
  Jako magazynier
  Chcę zarezerwować maszynę na konkretny okres dla budowy
  Aby montażysta mógł odebrać ją z magazynu w zaplanowanym terminie

  Scenariusz: Pomyślne utworzenie rezerwacji bez konfliktów
    Mając maszynę o UID "M-1001" ze statusem "W magazynie"
    Oraz budowę o numerze "BUD-2026-100" o nazwie "Most Wschodni"
    Kiedy magazynier tworzy rezerwację maszyny "M-1001" od "2026-06-01" do "2026-06-05" dla osoby "Anna Nowak"
    Wtedy rezerwacja jest utworzona ze statusem "oczekująca"
    Oraz w bazie jest dokładnie 1 rezerwacja
