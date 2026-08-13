#!/bin/bash
# =============================================================
# notification/templates.sh - MÓDULO 08 (NOTIFICATION)
# Converte um tipo de evento + payload JSON numa mensagem legível
# =============================================================

LOG_MODULE="notification"

# Uso: templates_render <event_type> <json_payload>
templates_render() {
    local type="$1" payload="$2"
    local j
    j() { echo "$payload" | jq -r "$1" 2>/dev/null; }

    case "$type" in
        mods_updated)
            echo "🔧 Mods atualizados no servidor $INSTANCE_NAME: $(j '.mods')"
            ;;
        backup_created)
            echo "💾 Backup criado: $(j '.file')"
            ;;
        backup_restored)
            echo "♻️ Backup restaurado: $(j '.file')"
            ;;
        server_restarted)
            echo "🔄 Servidor $(j '.instance') reiniciado"
            ;;
        server_recovered)
            echo "✅ Servidor $(j '.instance') voltou a responder (recuperado pelo watchdog)"
            ;;
        server_down)
            echo "🚨 Servidor $(j '.instance') está fora do ar (tentativa $(j '.attempt') de recuperação)"
            ;;
        task_failed)
            echo "❌ Tarefa agendada falhou: $(j '.task') (código $(j '.rc'))"
            ;;
        disk_low)
            echo "⚠️ Disco com apenas $(j '.free_pct')% livre no servidor $INSTANCE_NAME"
            ;;
        ram_low)
            echo "⚠️ RAM com apenas $(j '.free_pct')% livre no servidor $INSTANCE_NAME"
            ;;
        *)
            echo "ℹ️ [$type] $payload"
            ;;
    esac
}
