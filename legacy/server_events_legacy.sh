#!/usr/bin/env bash
# =============================================================
# DSM Core - Server Runtime
#
# Responsável: | Responsible:
#   Controle de processo DayZ | DayZ process control
#
# =============================================================

set -Eeuo pipefail

# -------------------------------------------------------------
# Retorna PID do DayZ
# Returns DayZ PID
# -------------------------------------------------------------
pid_get()
{
     local PID
        PID=$(pgrep -f "./DayZServer" | head -n1 || true)
        echo "$PID"
}

# -------------------------------------------------------------
# Verifica se servidor está online
# Checks if server is online
# -------------------------------------------------------------
server_is_online()
{
    local PID
    PID="$(pid_get)"

    if [[ -n "$PID" ]] && [[ -d "/proc/$PID" ]]
    then
        return 0
    fi

    return 1
}

# -------------------------------------------------------------
# Retorna uptime
# Returns uptime
# -------------------------------------------------------------
server_uptime()
{
    local PID
    PID="$(pid_get)"

    if [[ -n "$PID" ]]
    then
        ps -p "$PID" -o etime= | xargs
    else
        echo "00:00:00"
    fi
}


server_status_json()
{
    local FILE="${DSM_ROOT}/runtime/state/server.json"

    if [[ -f "$FILE" ]]
    then
        cat "$FILE"
    else
        echo '{}'
    fi
}



# -------------------------------------------------------------
# Export
# -------------------------------------------------------------
export -f pid_get
export -f server_is_online
export -f server_uptime
