#!/bin/bash
# =============================================================
# notification/notify.sh - MÓDULO 08 (NOTIFICATION)
# Agrega templates/discord/telegram/queue e expõe notify_dispatch,
# a função chamada por todos os outros módulos do DSM
# =============================================================

DSM_NOTIFY_DIR="${DSM_ROOT}/notification"

# shellcheck source=/dev/null
source "$DSM_NOTIFY_DIR/templates.sh"
# shellcheck source=/dev/null
source "$DSM_NOTIFY_DIR/discord.sh"
# shellcheck source=/dev/null
source "$DSM_NOTIFY_DIR/telegram.sh"
# shellcheck source=/dev/null
source "$DSM_NOTIFY_DIR/queue.sh"

LOG_MODULE="notification"

# Uso: notify_dispatch <event_type> <json_payload>
# Chamada por server/mods/backup/monitor/scheduler sempre que algo
# relevante acontece. Renderiza a mensagem uma vez e manda pra todos
# os canais configurados; o que falhar entra na fila de reenvio.
notify_dispatch() {
    local type="$1" payload="${2:-{}}"

    if ! discord_configured && ! telegram_configured; then
        return 0
    fi

    local message
    message="$(templates_render "$type" "$payload")"

    if discord_configured; then
        if ! discord_send "$message"; then
            log_warn "Falha ao enviar notificação para o Discord - enfileirando"
            queue_push "discord" "$message"
        fi
    fi

    if telegram_configured; then
        if ! telegram_send "$message"; then
            log_warn "Falha ao enviar notificação para o Telegram - enfileirando"
            queue_push "telegram" "$message"
        fi
    fi
}

notify_flush() {
    queue_flush
}
