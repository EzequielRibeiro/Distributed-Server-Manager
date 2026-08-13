#!/bin/bash
# =============================================================
# notification/queue.sh - MÓDULO 08 (NOTIFICATION)
# Fila de reenvio para notificações que falharam (webhook fora do
# ar, sem internet no momento etc.)
# =============================================================

LOG_MODULE="notification"

NOTIFY_QUEUE_FILE="${DSM_ROOT}/cache/notify_queue.log"

# Uso: queue_push <canal> <mensagem>
queue_push() {
    local channel="$1" message="$2"
    mkdir -p "$(dirname "$NOTIFY_QUEUE_FILE")"
    local encoded
    encoded="$(echo "$message" | base64 -w0)"
    echo "${channel}|${encoded}" >> "$NOTIFY_QUEUE_FILE"
    log_debug "Notificação enfileirada para reenvio (canal: $channel)"
}

queue_size() {
    [ -f "$NOTIFY_QUEUE_FILE" ] && wc -l < "$NOTIFY_QUEUE_FILE" || echo 0
}

# Tenta reenviar tudo que está na fila - remove da fila o que teve sucesso
queue_flush() {
    [ -f "$NOTIFY_QUEUE_FILE" ] || return 0
    [ -s "$NOTIFY_QUEUE_FILE" ] || return 0

    local tmp_file="${NOTIFY_QUEUE_FILE}.tmp"
    : > "$tmp_file"

    local sent=0 failed=0
    while IFS='|' read -r channel encoded; do
        [ -z "$channel" ] && continue
        local message
        message="$(echo "$encoded" | base64 -d 2>/dev/null)"

        local ok=1
        case "$channel" in
            discord)  discord_send "$message" && ok=0 ;;
            telegram) telegram_send "$message" && ok=0 ;;
        esac

        if [ "$ok" -eq 0 ]; then
            sent=$((sent + 1))
        else
            failed=$((failed + 1))
            echo "${channel}|${encoded}" >> "$tmp_file"
        fi
    done < "$NOTIFY_QUEUE_FILE"

    mv "$tmp_file" "$NOTIFY_QUEUE_FILE"

    if [ "$sent" -gt 0 ] || [ "$failed" -gt 0 ]; then
        log_info "Fila de notificações: $sent reenviada(s), $failed ainda pendente(s)"
    fi
}
