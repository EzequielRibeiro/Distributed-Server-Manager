#!/bin/bash
# =============================================================
# dashboard/api/server.sh - MÓDULO 09 (DASHBOARD)
#
# Endpoint de API: informações e ações sobre o servidor
# API Endpoint: information and actions about the server
#
# Uso | Usage: server.sh <status|start|stop|restart>
# =============================================================

DSM_ROOT="${DSM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# shellcheck source=/dev/null
source "$DSM_ROOT/core/bootstrap.sh" 2>/dev/null

BOOTSTRAP_RC=$?
if [ "$BOOTSTRAP_RC" -ne 0 ]; then
    echo '{"error":"falha ao carregar DSM bootstrap | failed to load DSM bootstrap"}'
    exit 1
fi

action="${1:-status}"
case "$action" in

    status)
        server_status_json
        ;;

    start)
        bash "$DSM_ROOT/server/start.sh" > /dev/null 2>&1
        server_status_json
        ;;

    stop)
        bash "$DSM_ROOT/server/stop.sh" > /dev/null 2>&1
        server_status_json
        ;;

    restart)
        bash "$DSM_ROOT/server/restart.sh" > /dev/null 2>&1
        server_status_json
        ;;

    *)
        echo "{\"error\":\"ação desconhecida | unknown action: $action\"}"
        exit 1
        ;;

esac
