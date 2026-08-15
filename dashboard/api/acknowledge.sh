#!/usr/bin/env bash

# =============================================================
# Capivara DSM Dashboard API
# Acknowledge Alert
#
# Fonte:
#   database/alert_store.sh
#
# Mantém o contrato HTTP legado enquanto a persistência passa
# a utilizar o Alert Store SQLite.
# =============================================================

set -u


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

ALERT_STORE="$DSM_ROOT/database/alert_store.sh"


api_header()
{
    echo "Content-Type: application/json"
    echo ""
}


json_response()
{
    local ok="$1"
    local message="$2"

    printf \
        '{"ok":%s,"message":"%s"}\n' \
        "$ok" \
        "$message"
}


get_alert_id()
{
    local argument="${1:-}"
    local id=""

    if [[ -n "$argument" ]]
    then
        id="$argument"
    elif [[ -n "${QUERY_STRING:-}" ]]
    then
        id="$(
            printf '%s' "$QUERY_STRING" |
            tr '&' '\n' |
            awk -F= '$1 == "id" {print $2; exit}'
        )"
    fi

    printf '%s\n' "$id"
}


acknowledge_alert()
{
    local id="$1"

    if [[ -z "$id" ]]
    then
        json_response \
            false \
            "ID do alerta não informado"
        return 2
    fi

    if [[ ! -f "$ALERT_STORE" ]]
    then
        json_response \
            false \
            "Alert Store não encontrado"
        return 2
    fi

    local result
    local status

    result="$(
        /bin/bash \
            "$ALERT_STORE" \
            ack \
            "$id" \
            2>&1
    )"

    status=$?

    if [[ $status -eq 0 ]]
    then
        json_response \
            true \
            "Alerta reconhecido"

        return 0
    fi

    json_response \
        false \
        "Não foi possível reconhecer alerta"

    return "$status"
}


main()
{
    case "${REQUEST_METHOD:-POST}" in

    POST|"")
        api_header

        ALERT_ID="$(
            get_alert_id \
                "${1:-}"
        )"

        acknowledge_alert \
            "$ALERT_ID"
        ;;

    *)
        api_header

        json_response \
            false \
            "Método não permitido"

        return 1
        ;;

    esac
}


main "$@"