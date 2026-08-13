#!/usr/bin/env bash

# =============================================================
# DSM Core - Server Runtime
#
# Controle de processos de servidores
#
# =============================================================

set -Eeuo pipefail


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

local HOST
local GAME
local INSTANCE


HOST="$(runtime_host)"
GAME="$(runtime_game)"
INSTANCE="$(runtime_instance)"


local FILE="${DSM_ROOT}/runtime/state/${HOST}/${GAME}/${INSTANCE}/server.json"


if [[ -f "$FILE" ]]
then
    cat "$FILE"
else
    echo '{}'
fi

}



export -f server_is_online
export -f server_uptime
export -f server_status_json