#!/usr/bin/env bash
#
# Kopia zapasowa bazy PostgreSQL projektu (pg_dump przez kontener docker compose).
# Zapisuje skompresowany zrzut do katalogu backups/ z sygnaturą czasową.
#
# Użycie:
#     ./scripts/backup_db.sh                 # zrzut bieżącej bazy
#     BACKUP_DIR=/tmp/kopie ./scripts/backup_db.sh
#
# Wymaga uruchomionego kontenera Postgres (`make db-up` / `docker compose up -d`).
set -euo pipefail

# Katalog projektu (rodzic katalogu scripts/) — komendy działają niezależnie od CWD.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Bezpieczny odczyt pojedynczej zmiennej z .env (BEZ wykonywania pliku — .env
# może zawierać wartości łamiące składnię basha, np. klucze API z nawiasami).
read_env() {
    [[ -f .env ]] || return 0
    grep -E "^${1}=" .env | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'
}

PG_USER="${POSTGRES_USER:-$(read_env POSTGRES_USER)}"; PG_USER="${PG_USER:-planer}"
PG_DB="${POSTGRES_DB:-$(read_env POSTGRES_DB)}"; PG_DB="${PG_DB:-planer_kursowy}"
SERVICE="${POSTGRES_SERVICE:-postgres}"
BACKUP_DIR="${BACKUP_DIR:-backups}"

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/planer-${PG_DB}-${TS}.sql.gz"

echo "Tworzę kopię bazy '${PG_DB}' → ${OUT}"
docker compose exec -T "$SERVICE" pg_dump -U "$PG_USER" -d "$PG_DB" --clean --if-exists \
    | gzip >"$OUT"

SIZE="$(du -h "$OUT" | cut -f1)"
echo "Gotowe. Rozmiar: ${SIZE}"
