#!/usr/bin/env bash

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

ACTION="${1:-}"
INSTANCE_PATH="${2:-}"

case "${ACTION}" in
    start|stop|restart|status)
        ;;
    *)
        echo '{"error":"invalid instance action"}' >&2
        exit 2
        ;;
esac

if [[ ! -d "${INSTANCE_PATH}" ]]
then
    echo '{"error":"instance not found"}' >&2
    exit 3
fi

# shellcheck source=/dev/null
source "${DSM_ROOT}/core/process/pid.sh"

# shellcheck source=/dev/null
source "${DSM_ROOT}/core/process/tree.sh"

# shellcheck source=/dev/null
source "${DSM_ROOT}/core/process/process.sh"


instance_publish_state()
{
    local INSTANCE_PATH="$1"

    local RELATIVE
    RELATIVE="${INSTANCE_PATH#${DSM_ROOT}/instances/}"

    local NODE
    local GAME
    local INSTANCE
    local EXTRA

    IFS='/' read -r \
        NODE \
        GAME \
        INSTANCE \
        EXTRA \
        <<< "${RELATIVE}"

    if [[ -z "${NODE:-}" ]] ||
       [[ -z "${GAME:-}" ]] ||
       [[ -z "${INSTANCE:-}" ]] ||
       [[ -n "${EXTRA:-}" ]]
    then
        return 1
    fi

    local STATE="offline"
    local HEALTH="offline"
    local PID=""

    if process_running "${INSTANCE_PATH}"
    then
        STATE="online"
        HEALTH="healthy"

        PID="$(
            process_pid "${INSTANCE_PATH}" 2>/dev/null ||
            true
        )"
    fi

    local RESOURCE
    RESOURCE="${DSM_ROOT}/runtime/resources/${NODE}/${GAME}/${INSTANCE}"

    mkdir -p "${RESOURCE}"

    local TMP
    TMP="$(
        mktemp \
            "${RESOURCE}/server.json.tmp.XXXXXX"
    )"

    jq -n \
        --arg state "${STATE}" \
        --arg health "${HEALTH}" \
        --arg pid "${PID}" \
        '{
            status: {
                state: $state,
                health: $health
            },
            pid: (
                if $pid == ""
                then null
                else ($pid | tonumber)
                end
            )
        }' \
        > "${TMP}"

    mv \
        "${TMP}" \
        "${RESOURCE}/server.json"
}


case "${ACTION}" in

    start)
        process_start "${INSTANCE_PATH}"
        instance_publish_state "${INSTANCE_PATH}"
        ;;

    stop)
        process_stop "${INSTANCE_PATH}"
        instance_publish_state "${INSTANCE_PATH}"
        ;;

    restart)
        process_restart "${INSTANCE_PATH}"
        instance_publish_state "${INSTANCE_PATH}"
        ;;

    status)
        process_status "${INSTANCE_PATH}"
        ;;

esac

printf '{"action":"%s","ok":true}\n' "${ACTION}"
