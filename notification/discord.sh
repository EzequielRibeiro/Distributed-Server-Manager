#!/bin/bash
# =============================================================
# notification/discord.sh - MÓDULO 08 (NOTIFICATION)
# Envio de mensagens via webhook do Discord
# =============================================================

LOG_MODULE="notification"

discord_configured() {
    [ -n "$DISCORD_WEBHOOK" ]
}

# Envia texto simples. Retorna 0 em sucesso, 1 em falha.
discord_send() {
    local message="$1"
    discord_configured || return 1

    local payload
    payload="$(jq -n --arg content "$message" '{content: $content}' 2>/dev/null)"
    [ -z "$payload" ] && payload="{\"content\":\"$(echo "$message" | sed 's/"/\\"/g')\"}"

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Content-Type: application/json" \
        -d "$payload" "$DISCORD_WEBHOOK" --max-time 10)

    [[ "$http_code" =~ ^2 ]]
}

discord_send_embed() {
    local title="$1" description="$2" color="${3:-3066993}"
    discord_configured || return 1

    local payload
    payload=$(jq -n --arg title "$title" --arg desc "$description" --argjson color "$color" \
        '{embeds: [{title: $title, description: $desc, color: $color}]}' 2>/dev/null)

    curl -s -o /dev/null -H "Content-Type: application/json" -d "$payload" "$DISCORD_WEBHOOK" --max-time 10
}
