#!/usr/bin/env bash
#
# Przywrócenie bazy PostgreSQL z kopii utworzonej przez backup_db.sh.
#
# Użycie:
#     ./scripts/restore_db.sh backups/planer-...-.sql.gz            # przywróć do bazy domyślnej (PYTA o potwierdzenie)
#     ./scripts/restore_db.sh backups/...sql.gz --force            # bez pytania
#     ./scripts/restore_db.sh backups/...sql.gz --target drill_db  # przywróć do innej (scratch) bazy
#
# OSTRZEŻENIE: przywrócenie NADPISUJE dane w bazie docelowej. Domyślnie skrypt
# prosi o potwierdzenie. Do prób (fire drill) używaj --target z bazą scratch.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Bezpieczny odczyt pojedynczej zmiennej z .env (BEZ wykonywania pliku).
read_env() {
    [[ -f .env ]] || return 0
    grep -E "^${1}=" .env | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'
}

PG_USER="${POSTGRES_USER:-$(read_env POSTGRES_USER)}"; PG_USER="${PG_USER:-planer}"
PG_DB="${POSTGRES_DB:-$(read_env POSTGRES_DB)}"; PG_DB="${PG_DB:-planer_kursowy}"
SERVICE="${POSTGRES_SERVICE:-postgres}"

BACKUP_FILE="${1:-}"
TARGET_DB="$PG_DB"
FORCE="no"

shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE="yes" ;;
        --target) TARGET_DB="$2"; shift ;;
        *) echo "Nieznany argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
    echo "Podaj istniejący plik kopii. Przykład: ./scripts/restore_db.sh backups/planer-...sql.gz" >&2
    exit 2
fi

if [[ "$FORCE" != "yes" ]]; then
    read -r -p "Przywrócić kopię do bazy '${TARGET_DB}'? To NADPISZE jej dane. [t/N] " ans
    [[ "$ans" == "t" || "$ans" == "T" ]] || { echo "Anulowano."; exit 0; }
fi

# Utwórz bazę docelową, jeśli nie istnieje (np. scratch do fire drillu).
docker compose exec -T "$SERVICE" psql -U "$PG_USER" -d postgres \
    -tc "SELECT 1 FROM pg_database WHERE datname='${TARGET_DB}'" | grep -q 1 \
    || docker compose exec -T "$SERVICE" createdb -U "$PG_USER" "$TARGET_DB"

echo "Przywracam ${BACKUP_FILE} → baza '${TARGET_DB}'..."
gunzip -c "$BACKUP_FILE" | docker compose exec -T "$SERVICE" psql -U "$PG_USER" -d "$TARGET_DB" -q
echo "Gotowe."
