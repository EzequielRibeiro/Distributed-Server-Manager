#!/bin/bash
# =============================================================
# dashboard/api/backup.sh - MÓDULO 09 (DASHBOARD)
# Endpoint API: Integra Dashboard com Backup Manager
# Uso: backup.sh <list|create|restore> [arquivo]
# =============================================================

DSM_ROOT="${DSM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# shellcheck source=/dev/null
source "$DSM_ROOT/core/bootstrap.sh" 2>/dev/null

BOOTSTRAP_RC=$?
if [ "$BOOTSTRAP_RC" -ne 0 ]; then
    echo '{"error":"falha ao carregar DSM bootstrap"}'
    exit 1
fi

action="${1:-list}"
arg="$2"

# =============================================================
# Execução
# =============================================================
case "$action" in
list)
    list_json
;;
create)
    if create_run > /dev/null 2>&1
    then
        list_json
    else
        echo '{"error":"falha ao criar backup"}'
        exit 1
    fi
;;
restore)
    if [ -z "$arg" ]
    then
        echo '{"error":"informe o nome do arquivo de backup"}'
        exit 1
    fi

    local_file="$BACKUP_DIR/$arg"
    if [ ! -f "$local_file" ]
    then
        echo '{"error":"backup não encontrado"}'
        exit 1
    fi

    if ! snapshot_create "pre_restore_dashboard" > /dev/null 2>&1
    then
        echo '{"error":"falha ao criar snapshot de segurança"}'
        exit 1
    fi

    if ! stop_run > /dev/null 2>&1
    then
        echo '{"error":"falha ao parar servidor antes do restore"}'
        exit 1
    fi

    if tar -xzf "$local_file" -C "$LGSM_DIR"
    then
        events_emit "backup.restored" "$arg (via dashboard)"
        echo "{\"ok\":true,\"file\":\"$arg\"}"
    else
        echo "{\"error\":\"falha ao restaurar backup\",\"file\":\"$arg\"}"
        exit 1
    fi
;;
*)
    echo "{\"error\":\"ação desconhecida: $action\"}"
    exit 1
;;
esac
