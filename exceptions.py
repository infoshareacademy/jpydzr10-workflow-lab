"""Wyjątki specyficzne dla aplikacji Planer Maszyn."""


class DataCorruptionError(Exception):
    """Plik danych i jego kopia zapasowa (.bak) są oba uszkodzone.

    Rzucany przez DataStore._load() gdy nie da się wczytać danych
    z żadnego źródła. Obsługiwany w ui.py przez App._safe_load(),
    gdzie wyświetla czytelny komunikat zamiast surowego traceback.

    Ważne: aplikacja NIE nadpisuje uszkodzonych plików pustą listą —
    dane pozostają na dysku do ręcznej naprawy.
    """

    def __init__(self, path: str, original_error: Exception):
        self.path = path
        self.original_error = original_error
        super().__init__(
            f"Plik {path} i kopia .bak są oba uszkodzone: {original_error}"
        )
