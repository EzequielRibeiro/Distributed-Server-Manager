#!/usr/bin/env bash
# =============================================================
# DSM Backup Worker
# Monitora continuamente o estado do módulo de Backup
# Atualiza: dashboard/state/backup_state.json
# =============================================================

set -Eeuo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_INTERVAL="${DSM_INTERVAL:-30}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
OUTPUT="${STATE_DIR}/backup_state.json"

mkdir -p "$STATE_DIR"
source "${DSM_ROOT}/core/lgsm.sh"
source "${DSM_ROOT}/core/backup.sh"

update_backup() {
    cat > "$OUTPUT" <<EOF
{
    "status":"$(backup_status)",
    "health":"$(backup_health)",
    "running":$(backup_running),
    "total":$(backup_total),
    "latest":{
        "name":"$(backup_latest_name)",
        "date":"$(backup_latest_date)",
        "size":"$(backup_latest_size)"
    },
    "total_size":"$(backup_total_size)",
    "last_result":"$(backup_last_result)",
    "next_schedule":"$(backup_next_schedule)",
    "generated_at":$(date +%s)
}
EOF
}

main() {
    while true
    do
        update_backup || true
        sleep "$DSM_INTERVAL"
    done
}
main
