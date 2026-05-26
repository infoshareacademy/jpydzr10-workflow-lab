# language: pl
Właściwość: Przeglądanie timeline rezerwacji
  Jako magazynier
  Chcę otworzyć widok timeline rezerwacji w przeglądarce
  Aby zobaczyć siatkę maszyn x dni z paskami rezerwacji

  Scenariusz: Zalogowany magazynier dostaje stronę timeline ze statusem 200
    Mając zalogowanego magazyniera
    Oraz maszynę o UID "M-5001" ze statusem "W magazynie"
    Kiedy magazynier wchodzi na adres "/rezerwacje/timeline/"
    Wtedy odpowiedź ma status HTTP 200

  Scenariusz: Parametr period=2week rozszerza widok do 14 dni
    Mając zalogowanego magazyniera
    Oraz maszynę o UID "M-5002" ze statusem "W magazynie"
    Kiedy magazynier wchodzi na adres "/rezerwacje/timeline/?period=2week&format=json"
    Wtedy odpowiedź zawiera 14 dni w polu day_list

  Scenariusz: Filtr ?machine_type ogranicza listę maszyn
    Mając zalogowanego magazyniera
    Oraz maszynę o UID "M-5010" typu "koparka"
    Oraz maszynę o UID "M-5011" typu "spawarka"
    Kiedy magazynier wchodzi na adres "/rezerwacje/timeline/?machine_type=koparka&format=json"
    Wtedy odpowiedź zawiera maszynę "M-5010" w machine_rows
    Oraz odpowiedź nie zawiera maszyny "M-5011" w machine_rows
