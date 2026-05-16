"""
WSGI config for planer_config project.

Eksponuje WSGI callable jako module-level zmienną `application`.

Domyślnie używa ustawień produkcyjnych. Dla dev używamy `manage.py runserver`,
który ma własny default (`planer_config.settings.dev`).
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "planer_config.settings.prod")

application = get_wsgi_application()
