#!/usr/bin/env bash
# =============================================================
# DSM Dashboard Worker
#
# server_worker.sh
#
# Responsável:
#   - Monitorar uma instância DSM
#   - Atualizar dashboard
#   - Publicar Runtime Resource
#   - Gerar eventos de servidor
#
# Modelo:
#
#   SERVER / GAME / INSTANCE
#
# Exemplo:
#
#   server01 / dayz / survival01
#
# =============================================================


set -Eeuo pipefail



DSM_ROOT="${DSM_ROOT:-/opt/dsm}"



# =============================================================
# Identidade do recurso
# =============================================================

source "${DSM_ROOT}/config/dsm.conf"

DSM_SERVER="${DSM_SERVER_ID}"
DSM_GAME="${DSM_GAME_ID}"
DSM_INSTANCE="${DSM_INSTANCE_ID}"



# =============================================================
# Runtime
# =============================================================

source "${DSM_ROOT}/core/lib/runtime.sh"

runtime_init



# =============================================================
# Event Engine
# =============================================================

source "${DSM_ROOT}/core/events.sh"



DSM_INTERVAL="${DSM_INTERVAL:-10}"



STATE_DIR="${DSM_ROOT}/dashboard/state"


OUTPUT="${STATE_DIR}/server_state.json"


LAST_STATE="${DSM_ROOT}/runtime/${DSM_SERVER}_${DSM_GAME}_${DSM_INSTANCE}.state"



PID_SCRIPT="${DSM_ROOT}/server/pid.sh"


STATUS_SCRIPT="${DSM_ROOT}/server/status.sh"



mkdir -p "$STATE_DIR"



# =============================================================
# Estado anterior
# =============================================================

get_last_state()
{

    if [ -f "$LAST_STATE" ]
    then

        cat "$LAST_STATE"

    else

        echo "UNKNOWN"

    fi

}



save_last_state()
{

    echo "$1" > "$LAST_STATE"

}



# =============================================================
# PID
# =============================================================

get_server_pid()
{

    DSM_ROOT="$DSM_ROOT" \
    bash "$PID_SCRIPT" \
    2>/dev/null || echo 0

}



# =============================================================
# Status
# =============================================================

get_server_status()
{

    DSM_ROOT="$DSM_ROOT" \
    bash "$STATUS_SCRIPT" \
    2>/dev/null || echo OFFLINE

}



# =============================================================
# Eventos
# =============================================================

process_event()
{

    local OLD_STATE="$1"

    local NEW_STATE="$2"



    if [ "$OLD_STATE" = "$NEW_STATE" ]
    then
        return
    fi



    case "$NEW_STATE" in


        ONLINE)

            if [ "$OLD_STATE" = "OFFLINE" ] ||
               [ "$OLD_STATE" = "UNKNOWN" ]
            then

                event_info \
                SERVER_START \
                server \
                "Servidor iniciado" \
                "$DSM_SERVER" \
                "$DSM_GAME" \
                "$DSM_INSTANCE"

            fi

        ;;



        OFFLINE)


            if [ "$OLD_STATE" = "ONLINE" ]
            then

                event_info \
                SERVER_STOP \
                server \
                "Servidor parado" \
                "$DSM_SERVER" \
                "$DSM_GAME" \
                "$DSM_INSTANCE"

            fi

        ;;

    esac

}



# =============================================================
# Atualização
# =============================================================

update_server()
{

    local PID

    local STATUS

    local OLD_STATE

    local HEALTH

    local UPTIME



    PID=$(get_server_pid)


    STATUS=$(get_server_status)


    OLD_STATE=$(get_last_state)



    if [[ "$STATUS" == "ONLINE" ]] &&
       [[ "$PID" != "0" ]]
    then

        HEALTH="healthy"


        UPTIME=$(ps -p "$PID" \
        -o etime= \
        2>/dev/null \
        | xargs)



    else


        PID="null"

        HEALTH="critical"

        UPTIME="00:00:00"

        STATUS="OFFLINE"


    fi



    process_event \
    "$OLD_STATE" \
    "$STATUS"



    save_last_state "$STATUS"



cat > "$OUTPUT" <<EOF
{
    "identity": {
        "server": "$DSM_SERVER",
        "game": "$DSM_GAME",
        "instance": "$DSM_INSTANCE"
    },

    "status": {
        "state": "$(echo "$STATUS" | tr '[:upper:]' '[:lower:]')",
        "health": "$HEALTH",
        "pid": $PID,
        "uptime": "$UPTIME"
    },

    "players": {
        "current": 0,
        "max": 60
    },

    "last_check": $(date +%s)
}
EOF



    # Runtime multi recurso

    runtime_set_resource \
    "$DSM_SERVER" \
    "$DSM_GAME" \
    "$DSM_INSTANCE" \
     server \
    "$(cat "$OUTPUT")"



}



# =============================================================
# Loop
# =============================================================

while true
do

    update_server || true

    sleep "$DSM_INTERVAL"

done