#!/usr/bin/env bash
# =============================================================
# DSM Dashboard API
# monitor.sh
# Endpoints: status, events, doctor
# Responsável por retornar os estados produzidos pelos workers.
# =============================================================

set -Eeuo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
ACTION="${1:-status}"

# -------------------------------------------------------------
# Retorna um arquivo JSON de estado
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
    send_state "${STATE_DIR}/monitor_state.json"
;;
events)
    send_state "${STATE_DIR}/events_state.json"
;;
doctor)
    send_state "${STATE_DIR}/doctor_state.json"
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
