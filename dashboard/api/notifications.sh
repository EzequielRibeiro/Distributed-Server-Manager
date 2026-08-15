#!/usr/bin/env bash

# =============================================================
# Capivara DSM Dashboard API
# Notifications
#
# Fonte:
#   database/alert_store.sh
#
# Contrato HTTP legado preservado.
# =============================================================

set -u


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

ALERT_STORE="$DSM_ROOT/database/alert_store.sh"


json_error()
{
    local message="${1:-unknown error}"

    printf '%s\n' \
        "{\"total\":0,\"critical\":0,\"warning\":0,\"alerts\":[],\"error\":\"${message}\"}"
}


if [[ ! -f "$ALERT_STORE" ]]
then
    json_error \
        "Alert Store não encontrado"
    exit 1
fi


action="${1:-list}"


case "$action" in

list)
    alerts="$(
        /bin/bash \
            "$ALERT_STORE" \
            active \
            2>/dev/null
    )"

    status=$?

    if [[ $status -ne 0 ]]
    then
        json_error \
            "Falha ao consultar Alert Store"
        exit "$status"
    fi

    if ! printf '%s' "$alerts" |
        jq -e 'type == "array"' \
            >/dev/null 2>&1
    then
        alerts='[]'
    fi

    printf '%s\n' "$alerts" |
    jq '{
        total: length,
        critical: (
            [
                .[]
                | select(
                    (
                        .level
                        // ""
                        | ascii_upcase
                    )
                    == "CRITICAL"
                )
            ]
            | length
        ),
        warning: (
            [
                .[]
                | select(
                    (
                        .level
                        // ""
                        | ascii_upcase
                    )
                    == "WARNING"
                )
            ]
            | length
        ),
        alerts: .
    }'
    ;;


active)
    /bin/bash \
        "$ALERT_STORE" \
        active
    ;;


history)
    /bin/bash \
        "$ALERT_STORE" \
        history
    ;;


count)
    /bin/bash \
        "$ALERT_STORE" \
        count
    ;;


ack|acknowledge)
    id="${2:-}"

    if [[ -z "$id" ]]
    then
        printf '%s\n' \
            '{"ok":false,"error":"id obrigatório"}'
        exit 1
    fi

    /bin/bash \
        "$ALERT_STORE" \
        ack \
        "$id"
    ;;


*)
    printf \
        '{"error":"ação inválida","action":"%s"}\n' \
        "$action"

    exit 1
    ;;

esac