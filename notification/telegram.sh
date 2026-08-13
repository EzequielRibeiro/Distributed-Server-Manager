#!/bin/bash
# =============================================================
# notification/telegram.sh - MÓDULO 08 (NOTIFICATION)
# Envio de mensagens via Telegram Bot API
# =============================================================

LOG_MODULE="notification"

telegram_configured() {
    [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]
}

# Envia texto simples. Retorna 0 em sucesso, 1 em falha.
telegram_send() {
    local message="$1"
    telegram_configured || return 1

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${message}")

    [[ "$http_code" =~ ^2 ]]
}
