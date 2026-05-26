#!/usr/bin/env bash
# =============================================================================
# Skrypt pierwszego uruchomienia środowiska deweloperskiego (one-shot).
#
# Co robi:
#   1. Startuje PostgreSQL w Dockerze (port 5433).
#   2. Czeka aż DB odpowie na pg_isready.
#   3. Aplikuje migracje Django.
#   4. Tworzy konto superusera (sebastian / Planer2026!) jeśli nie istnieje.
#
# Uruchomienie:
#   bash scripts/setup_dev.sh
#
# Następnie:
#   uv run python manage.py runserver
# =============================================================================
set -euo pipefail

echo "Startuje PostgreSQL (planer-reference-postgres na porcie 5433)..."
docker-compose up -d

echo "Czekam na gotowość bazy..."
for i in {1..30}; do
    if docker exec planer-reference-postgres pg_isready -U planer >/dev/null 2>&1; then
        echo "Baza gotowa."
        break
    fi
    sleep 1
done

echo "Aplikuje migracje..."
uv run python manage.py migrate

echo "Tworzenie superusera (sebastian / Planer2026!)..."
uv run python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='sebastian').exists():
    User.objects.create_superuser('sebastian', 'sebastian@planer.local', 'Planer2026!')
    print('Superuser utworzony.')
else:
    print('Superuser juz istnieje.')
"

echo ""
echo "Setup zakonczony. Uruchom serwer:"
echo "  uv run python manage.py runserver"
