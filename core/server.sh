#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Server Runtime Controller
#
# Native Runtime Engine
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

export DSM_ROOT


# -------------------------------------------------------------
# Config
# -------------------------------------------------------------

source "${DSM_ROOT}/config/runtime.sh"


# -------------------------------------------------------------
# Runtime Context
# -------------------------------------------------------------

source "${DSM_ROOT}/core/runtime/context.sh"


# -------------------------------------------------------------
# Resources
# -------------------------------------------------------------

source "${DSM_ROOT}/core/lib/resources.sh"




server_context_load()
{

: "${GAME_ID:=${GAME:-}}"

: "${DSM_INSTANCE_ID:=${INSTANCE_ID:-}}"


if [[ -z "${GAME_ID}" ]]
then
    echo "GAME_ID não definido"
    exit 1
fi


if [[ -z "${DSM_INSTANCE_ID}" ]]
then
    echo "DSM_INSTANCE_ID não definido"
    exit 1
fi


export GAME_ID
export DSM_INSTANCE_ID

}



pid_get()
{

local PROCESS


case "$(runtime_game)" in


    DayZ|dayz)

        PROCESS="./DayZServer"
        ;;


    Arma3|arma3)

        PROCESS="./arma3server"
        ;;


    *)

        PROCESS=""

        ;;

esac



if [[ -n "$PROCESS" ]]
then

    pgrep -f "$PROCESS" | head -n1 || true

else

    echo ""

fi

}


export -f pid_get

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

local HOST
local GAME
local INSTANCE


HOST="$(runtime_host)"
GAME="$(runtime_game)"
INSTANCE="$(runtime_instance)"


local FILE="${DSM_ROOT}/runtime/state/$HOST/$GAME/$INSTANCE/server.json"


if [[ -f "$FILE" ]]
then

    cat "$FILE"

else

    echo '{}'

fi

}

server_state_update()
{
    local PID
    PID="$(pid_get)"


    local STATE="offline"
    local HEALTH="critical"


    if server_is_online
    then
        STATE="online"
        HEALTH="healthy"
    fi



    local JSON


    JSON=$(cat <<EOF
{
    "identity": {
        "host": "$(runtime_host)",
        "node": "$(runtime_node)",
        "game": "$(runtime_game)",
        "instance": "$(runtime_instance)"
    },
    "status": {
        "state": "$STATE",
        "health": "$HEALTH",
        "pid": ${PID:-0},
        "uptime": "$(server_uptime)"
    },
    "players": {
        "current": 0,
        "max": 60
    },
    "last_check": $(date +%s)
}
EOF
    )

    echo "$JSON" | jq empty || return 1

    runtime_update_resource \
    "$(runtime_host)" \
    "$(runtime_game)" \
    "$(runtime_instance)" \
    "server" \
    "$JSON"
}


# -------------------------------------------------------------
# Export
# -------------------------------------------------------------
export -f pid_get
export -f server_is_online
export -f server_uptime
export -f server_state_update
export -f server_status_json