"""
Konfiguracja pytest — dodaje katalog projektu do PYTHONPATH.

TODO (Milestone 2): Zastąpić tym wpisem w pyproject.toml:
    [tool.pytest.ini_options]
    pythonpath = ["."]
"""

import sys
import os

# Dodaj katalog projektu do PYTHONPATH, żeby testy mogły importować moduły
sys.path.insert(0, os.path.dirname(__file__))
