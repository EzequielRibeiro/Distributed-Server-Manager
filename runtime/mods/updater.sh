#!/bin/bash
# =============================================================
# DSM Runtime Mods Updater
#
# Commit 15.4
#
# Responsável por:
# - manter estado atual dos Mods
# - consumir eventos MOD
# - atualizar runtime/mods/state.json
#
# Eventos suportados:
#
# MOD_UPDATED
# MOD_MISSING
# KEY_MISSING
# MOD_UPDATE_FAILED
#
# =============================================================


set -e


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


STATE_DIR="${DSM_ROOT}/runtime/mods"
STATE_FILE="${STATE_DIR}/state.json"


mkdir -p "${STATE_DIR}"


init()
{
    if [ ! -f "${STATE_FILE}" ]
    then
        echo "{}" > "${STATE_FILE}"
    fi


    if ! jq empty "${STATE_FILE}" >/dev/null 2>&1
    then
        echo "{}" > "${STATE_FILE}"
    fi
}



extract_mod()
{
    local message="$1"

    echo "${message}" \
    | sed \
    -E \
    's/^@([^ ]+).*/\1/'
}



extract_status()
{
    local type="$1"

    case "${type}" in

        MOD_UPDATED)
            echo "MOD_UPDATED"
        ;;

        MOD_MISSING)
            echo "MOD_MISSING"
        ;;

        KEY_MISSING)
            echo "KEY_MISSING"
        ;;

        MOD_UPDATE_FAILED)
            echo "MOD_UPDATE_FAILED"
        ;;

        *)
            echo "UNKNOWN"
        ;;

    esac
}



update_mod()
{
    local type="$1"
    local message="$2"
    local timestamp="$3"


    local mod
    mod=$(extract_mod "${message}")


    if [ -z "${mod}" ]
    then
        return
    fi


    local status
    status=$(extract_status "${type}")


    local TMP
    TMP=$(mktemp)


    jq \
    --arg mod "${mod}" \
    --arg status "${status}" \
    --arg message "${message}" \
    --argjson timestamp "${timestamp}" \
'
.[$mod] =
{
    status:$status,
    last_event:$message,
    updated:$timestamp
}
' \
"${STATE_FILE}" \
> "${TMP}"


    mv "${TMP}" "${STATE_FILE}"
}



consume_event()
{
    local event="$1"


    local type
    local message
    local timestamp


    type=$(echo "${event}" | jq -r '.type')

    message=$(echo "${event}" \
        | jq -r '.data.message')


    timestamp=$(echo "${event}" \
        | jq -r '.timestamp')


    case "${type}" in

        MOD_UPDATED|MOD_MISSING|KEY_MISSING|MOD_UPDATE_FAILED)

            update_mod \
            "${type}" \
            "${message}" \
            "${timestamp}"

        ;;

    esac
}



process_file()
{
    local file="$1"


    if [ ! -f "${file}" ]
    then
        return
    fi


    jq -c '.[]' "${file}" \
    | while read -r event
    do
        consume_event "${event}"
    done
}



init



case "${1:-}" in


event)

    consume_event "$2"

;;


file)

    process_file "$2"

;;


*)

echo
echo "DSM Runtime Mods Updater"
echo
echo "Uso:"
echo
echo " updater.sh event JSON"
echo " updater.sh file EVENT_FILE"
echo

exit 1

;;

esac