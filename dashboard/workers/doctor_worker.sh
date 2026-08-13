#!/usr/bin/env bash
# =============================================================
# DSM Doctor Worker
# Executa verificações periódicas do ambiente DSM
# Atualiza: dashboard/state/doctor_state.json
# =============================================================

set -Eeuo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_INTERVAL="${DSM_INTERVAL:-60}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
OUTPUT="${STATE_DIR}/doctor_state.json"

mkdir -p "$STATE_DIR"
source "${DSM_ROOT}/core/lgsm.sh"

doctor_run() {
    local SERVER_STATUS
    local SERVER_HEALTH
    SERVER_STATUS="$(lgsm_status)"

    if [[ "$SERVER_STATUS" == "online" ]]
    then
        SERVER_HEALTH="ok"
    else
        SERVER_HEALTH="fail"
    fi

    cat > "$OUTPUT" <<EOF
{
    "generated_at": $(date +%s),
    "overall": "$SERVER_HEALTH",
    "checks": {
        "linuxgsm": { "status": "ok" },
        "server": { "status": "$SERVER_HEALTH" },
        "serverfiles": { "status": "$(lgsm_serverfiles_status)" },
        "config": { "status": "$(lgsm_config_status)" },
        "mods": { "status": "$(lgsm_mods_status)" },
        "keys": { "status": "$(lgsm_keys_status)" },
        "permissions": { "status": "$(lgsm_permissions_status)" }
    }
}
EOF
}

main() {
    while true
    do
        doctor_run || true
        sleep "$DSM_INTERVAL"
    done
}
main
