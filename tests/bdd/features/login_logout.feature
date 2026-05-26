# language: pl
Właściwość: Logowanie i wylogowywanie pracownika
  Aby zarządzać systemem
  Jako pracownik
  Chcę zalogować się do aplikacji i bezpiecznie ją opuścić

  Scenariusz: Pomyślne zalogowanie magazyniera
    Mając użytkownika "magazynier_login" z hasłem "Tajne123!Pass"
    Kiedy magazynier wchodzi na stronę logowania
    Oraz podaje login "magazynier_login" i hasło "Tajne123!Pass"
    Wtedy zostaje przekierowany na stronę główną
    Oraz jest zalogowany

  Scenariusz: Logowanie z błędnym hasłem
    Mając użytkownika "magazynier_login2" z hasłem "Tajne123!Pass"
    Kiedy magazynier podaje login "magazynier_login2" i hasło "ZupelnieZle123!"
    Wtedy widzi błąd logowania
    Oraz nie jest zalogowany

  Scenariusz: Wylogowanie kończy sesję
    Mając zalogowanego użytkownika "magazynier_logout"
    Kiedy magazynier wylogowuje się
    Wtedy nie jest zalogowany
