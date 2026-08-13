#!/usr/bin/env bash
# =============================================================
# DSM Dashboard API
# scheduler.sh
# Endpoints: status
# Responsável por retornar os estados produzidos pelo scheduler_worker.sh
# =============================================================

set -Eeuo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
ACTION="${1:-status}"

# -------------------------------------------------------------
# Retorna arquivo JSON
# -------------------------------------------------------------
send_state() {
    local FILE="$1"
    if [[ -f "$FILE" ]]
    then
        cat "$FILE"
    else
        cat <<EOF
{
    "status":"unknown",
    "message":"Arquivo de estado não encontrado",
    "updated_at":0
}
EOF
    fi
}

# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------
case "$ACTION" in
status)
    send_state "${STATE_DIR}/scheduler_state.json"
;;
*)
    cat <<EOF
{
    "status":"error",
    "message":"Ação desconhecida: ${ACTION}"
}
EOF
    exit 1
;;
esac
