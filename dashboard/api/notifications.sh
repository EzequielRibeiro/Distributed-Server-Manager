#!/usr/bin/env bash
# =============================================================
# Capivara DSM Dashboard API
# Notifications
#
# Fonte única:
#   core/notification_center.sh
# =============================================================

set -u

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
NOTIFICATION_CENTER="$DSM_ROOT/core/notification_center.sh"

if [ ! -x "$NOTIFICATION_CENTER" ]; then
    printf '%s\n' \
        '{"total":0,"critical":0,"warning":0,"alerts":[],"error":"Notification Center não encontrado"}'
    exit 1
fi

action="${1:-list}"

case "$action" in

list)
    alerts="$("$NOTIFICATION_CENTER" active 2>/dev/null)"

    if ! printf '%s' "$alerts" | jq -e 'type == "array"' >/dev/null 2>&1; then
        alerts='[]'
    fi

    printf '%s\n' "$alerts" |
    jq '{
        total: length,
        critical: ([.[] | select((.level // "" | ascii_upcase) == "CRITICAL")] | length),
        warning: ([.[] | select((.level // "" | ascii_upcase) == "WARNING")] | length),
        alerts: .
    }'
    ;;

active)
    "$NOTIFICATION_CENTER" active
    ;;

history)
    "$NOTIFICATION_CENTER" history
    ;;

count)
    "$NOTIFICATION_CENTER" count
    ;;

ack|acknowledge)
    id="${2:-}"

    if [ -z "$id" ]; then
        echo '{"ok":false,"error":"id obrigatório"}'
        exit 1
    fi

    "$NOTIFICATION_CENTER" ack "$id"
    printf '{"ok":true,"id":"%s"}\n' "$id"
    ;;

*)
    printf '{"error":"ação inválida","action":"%s"}\n' "$action"
    exit 1
    ;;

esac
