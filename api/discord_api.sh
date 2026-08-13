#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
# Arquivo:
#   api/discord_api.sh
# Função:
#   API Dashboard -> Discord
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

CONFIG="$DSM_ROOT/config/discord_config.sh"
TEST="$DSM_ROOT/core/discord_test.sh"
WEBHOOK="$DSM_ROOT/core/discord_webhook.sh"
SENDER="$DSM_ROOT/core/discord_sender.sh"

# -------------------------------------------------------------
# Headers JSON
# -------------------------------------------------------------
json_header() {
    echo "Content-Type: application/json"
    echo ""
}

# -------------------------------------------------------------
# Resposta JSON
# -------------------------------------------------------------
json_response() {
    local status="$1"
    local message="$2"

    jq -n \
        --arg status "$status" \
        --arg message "$message" \
        '
{
 status:$status,
 message:$message,
 timestamp:(now|todate)
}
'
}

# -------------------------------------------------------------
# Status Discord
# -------------------------------------------------------------
discord_status() {
    if [ ! -f "$CONFIG" ]; then
        json_response "ERROR" "Configuração Discord ausente"
        return
    fi

    source "$CONFIG"

    if discord_init
    then
        jq -n \
            --arg enabled "$DISCORD_ENABLED" \
            --arg channel "$DISCORD_CHANNEL" \
            --arg bot "$DISCORD_USERNAME" \
            '
{
 status:"ONLINE",
 enabled:$enabled,
 channel:$channel,
 bot:$bot
}
'
    else
        json_response "OFFLINE" "Discord não configurado"
    fi
}

# -------------------------------------------------------------
# Teste webhook
# -------------------------------------------------------------
discord_test() {
    if "$TEST" webhook >/dev/null
    then
        json_response "OK" "Mensagem de teste enviada ao Discord"
    else
        json_response "ERROR" "Falha no envio Discord"
    fi
}

# -------------------------------------------------------------
# Envio manual
# -------------------------------------------------------------
discord_send() {
    local message="$1"

    if [ -z "$message" ]; then
        json_response "ERROR" "Mensagem vazia"
        return
    fi

    if "$WEBHOOK" message "$message"
    then
        json_response "OK" "Mensagem enviada"
    else
        json_response "ERROR" "Falha no envio"
    fi
}

# -------------------------------------------------------------
# Obter POST
# -------------------------------------------------------------
read_post() {
    if [ -n "$CONTENT_LENGTH" ]; then
        head -c "$CONTENT_LENGTH"
    fi
}

# -------------------------------------------------------------
# Router
# -------------------------------------------------------------
PATH_INFO="${PATH_INFO:-$1}"

case "$PATH_INFO" in
status)
    json_header
    discord_status
;;
test)
    json_header
    discord_test
;;
send)
    json_header
    BODY=$(read_post)
    MESSAGE=$(echo "$BODY" | jq -r '.message')
    discord_send "$MESSAGE"
;;
*)
    json_header
    json_response "ERROR" "Endpoint inexistente"
;;
esac
