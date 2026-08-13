#!/usr/bin/env bash
# =============================================================
# DSM Dashboard API
#
# backups.sh
#
# Retorna informações dos backups em formato JSON.
#
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
BACKUP_DIR="${DSM_BACKUP_DIR:-/opt/dsm-backup}"

# =============================================================
# Verificações
# =============================================================

if [[ ! -d "$BACKUP_DIR" ]]; then
    cat <<EOF
{
    "total": 0,
    "last_backup": "",
    "last_date": "",
    "total_size": "0 B",
    "status": "NOT_FOUND"
}
EOF
    exit 0
fi

# =============================================================
# Arquivos de backup
# =============================================================

mapfile -t BACKUPS < <(
    find "$BACKUP_DIR" \
        -maxdepth 1 \
        -type f \
        -name "*.tar.gz" \
        | sort
)

TOTAL="${#BACKUPS[@]}"

# =============================================================
# Nenhum backup
# =============================================================

if (( TOTAL == 0 )); then
    cat <<EOF
{
    "total": 0,
    "last_backup": "",
    "last_date": "",
    "total_size": "0 B",
    "status": "EMPTY"
}
EOF
    exit 0
fi

# =============================================================
# Último backup
# =============================================================

LAST_FILE="$(printf '%s\n' "${BACKUPS[@]}" | sort | tail -n1)"
LAST_NAME="$(basename "$LAST_FILE")"

LAST_DATE="$(date -r "$LAST_FILE" '+%Y-%m-%d %H:%M:%S')"

# =============================================================
# Tamanho total
# =============================================================

TOTAL_SIZE="$(du -sh "$BACKUP_DIR" | awk '{print $1}')"

# =============================================================
# JSON
# =============================================================

cat <<EOF
{
    "total": $TOTAL,
    "last_backup": "$LAST_NAME",
    "last_date": "$LAST_DATE",
    "total_size": "$TOTAL_SIZE",
    "status": "OK"
}
EOF