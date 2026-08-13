#!/bin/bash
# =============================================================
# dashboard/api/mods.sh - MÓDULO 09 (DASHBOARD)
#
# Endpoint API: Integra Dashboard com Mods Manager
# API Endpoint: Integrates Dashboard with Mods Manager
#
# Uso | Usage: mods.sh <list|update|verify|rollback> [id]
# =============================================================

DSM_ROOT="${DSM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# shellcheck source=/dev/null
source "$DSM_ROOT/core/bootstrap.sh" 2>/dev/null
# Carrega estado do módulo Mods | Load Mods module state
source "$DSM_ROOT/mods/state.sh"

BOOTSTRAP_RC=$?
if [ "$BOOTSTRAP_RC" -ne 0 ]; then
    echo '{"error":"falha ao carregar DSM bootstrap | failed to load DSM bootstrap"}'
    exit 1
fi

action="${1:-list}"
arg="${2:-}"

# -------------------------------------------------------------
# Lista mods em JSON | List mods in JSON
# -------------------------------------------------------------
mods_list_json() {

    if [ ! -f "$STATE_FILE" ]
    then
        cat <<EOF
{
    "total": 0,
    "mods": [],
    "status": "EMPTY",
    "last_update": 0
}
EOF
        return 0
    fi


    MODS=$(jq -R -s '
    split("\n")
    | map(
        select(length > 0)
        | split("|")
        | {
            id: .[0],
            timestamp: .[1],
            folder: .[2],
            installed_at: .[3]
          }
      )
    ' "$STATE_FILE")


    TOTAL=$(echo "$MODS" | jq length)


    cat <<EOF
{
    "total": $TOTAL,
    "mods": $MODS,
    "status": "OK",
    "last_update": $(date +%s)
}
EOF
}

# -------------------------------------------------------------
# Execução | Execution
# -------------------------------------------------------------
case "$action" in
list)
    mods_list_json
;;
update)
    if updater_run > /dev/null 2>&1
    then
        mods_list_json
    else
        echo '{"error":"falha ao atualizar mods | failed to update mods"}'
        exit 1
    fi
;;
verify)
    if verify_run > /dev/null 2>&1
    then
        echo '{"ok":true,"action":"verify"}'
    else
        echo '{"error":"falha ao verificar mods | failed to verify mods"}'
        exit 1
    fi
;;
rollback)
    if [ -z "$arg" ]
    then
        echo '{"error":"informe o id do mod | provide the mod id"}'
        exit 1
    fi

    if updater_rollback "$arg" > /dev/null 2>&1
    then
        echo "{\"ok\":true,\"id\":\"$arg\"}"
    else
        echo "{\"error\":\"falha no rollback | failed to rollback\",\"id\":\"$arg\"}"
        exit 1
    fi
;;
*)
    echo "{\"error\":\"ação desconhecida | unknown action: $action\"}"
    exit 1
;;
esac
