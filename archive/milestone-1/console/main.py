"""
Planer Maszyn Budowlanych — punkt wejścia.

Uruchomienie: python main.py
"""

from ui import App

if __name__ == "__main__":
    try:
        App().run()
    except KeyboardInterrupt:
        print("\n\n  Przerwano (Ctrl+C). Do widzenia!")
    except EOFError:
        print("\n\n  Koniec wejścia. Do widzenia!")
