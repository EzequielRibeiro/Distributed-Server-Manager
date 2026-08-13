#!/usr/bin/env bash
# =============================================================
# DSM
# monitor/diagnose.sh
# Monitor do servidor
# Responsável por exibir o estado atual do monitoramento
# e do watchdog.
# Não executa diagnósticos completos.
# Para isso utilize:
#   dsm doctor
# =============================================================

set -Eeuo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
SERVER_STATE="${STATE_DIR}/server_state.json"
METRICS_STATE="${STATE_DIR}/metrics_state.json"
MONITOR_STATE="${STATE_DIR}/monitor_state.json"
EVENTS_STATE="${STATE_DIR}/events_state.json"
METRICS_STATE="${STATE_DIR}/metrics_state.json"

# -------------------------------------------------------------
# Utilitário
# -------------------------------------------------------------
json_value()
{
    local FILE="$1"
    local KEY="$2"

    [[ -f "$FILE" ]] || {
        echo "-"
        return
    }

    python3 - <<EOF
import json

try:
    with open("$FILE") as f:
        data=json.load(f)
    print(data.get("$KEY","-"))
except Exception:
    print("-")
EOF
}

# -------------------------------------------------------------
# Execução principal
# -------------------------------------------------------------
monitor_diagnose_run()
{
    local SERVER_STATUS
    local HEALTH
    local PID
    local CPU
    local MEMORY
    local DISK
    local EVENTS
    local LAST_CHECK

    SERVER_STATUS=$(json_value "$SERVER_STATE" status)
    HEALTH=$(json_value "$SERVER_STATE" health)
    PID=$(json_value "$SERVER_STATE" pid)

    CPU=$(metrics_value "cpu.host_pct")
    MEMORY=$(metrics_value "memory.dayz_pct")
    DISK=$(metrics_value "disk.used_pct")

    EVENTS=$(json_value "$EVENTS_STATE" total)
    LAST_CHECK=$(json_value "$SERVER_STATE" last_check)

    echo
    echo "============================================================"
    echo " DSM - Monitor"
    echo "============================================================"
    echo
    printf "%-24s %s\n" "Servidor:"          "$SERVER_STATUS"
    printf "%-24s %s\n" "Health:"            "$HEALTH"
    printf "%-24s %s\n" "PID:"               "$PID"
    printf "%-24s %s%%\n" "CPU:"             "$CPU"
    printf "%-24s %s%%\n" "Memória:"         "$MEMORY"
    printf "%-24s %s%%\n" "Disco:"           "$DISK"
    printf "%-24s %s\n" "Eventos:"          "$EVENTS"
    printf "%-24s %s\n" "Última verificação:" "$LAST_CHECK"
    echo

    if [[ "$SERVER_STATUS" == "online" ]]
    then
        echo "Status geral............... OK"
        return 0
    fi

    echo "Status geral............... ALERTA"
    return 1
}

# -------------------------------------------------------------
# Compatibilidade
# -------------------------------------------------------------
diagnose_run()
{
    monitor_diagnose_run "$@"
}


metrics_value()
{
    local KEY="$1"

    python3 - "$METRICS_STATE" "$KEY" <<'PY'
import json
import sys

file=sys.argv[1]
key=sys.argv[2]

try:
    with open(file) as f:
        data=json.load(f)

    value=data

    for part in key.split("."):
        value=value.get(part)

    if value is None:
        print("-")
    else:
        print(value)

except Exception:
    print("-")
PY
}


# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    monitor_diagnose_run "$@"
fi
