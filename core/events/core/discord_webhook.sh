#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
#
# Arquivo:
#   core/discord_webhook.sh
#
# Função:
#   Comunicação direta com Discord Webhook
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

CONFIG="$DSM_ROOT/config/discord_config.sh"
LOG_FILE="$DSM_ROOT/logs/discord.log"

# -------------------------------------------------------------
# Carregar configuração
# -------------------------------------------------------------
load_config()
{
    if [ ! -f "$CONFIG" ]; then
        echo "[DSM] Configuração Discord inexistente"
        exit 1
    fi

    source "$CONFIG"
    discord_init
}

# -------------------------------------------------------------
# Criar diretório de log
# -------------------------------------------------------------
prepare_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"
}

# -------------------------------------------------------------
# Registrar log
# -------------------------------------------------------------
discord_log()
{
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
    >> "$LOG_FILE"
}

# -------------------------------------------------------------
# Enviar mensagem simples
# -------------------------------------------------------------
send_message()
{
    local message="$1"

    if [ -z "$message" ]; then
        discord_log "Mensagem vazia"
        return 1
    fi

    local payload
    payload=$(jq -n \
        --arg content "$message" \
        '
        {
          content:$content
        }
        '
    )

    http_code=$(curl \
        -s \
        -o /tmp/dsm_discord_response \
        -w "%{http_code}" \
        -H "Content-Type: application/json" \
        -X POST \
        -d "$payload" \
        "$DISCORD_WEBHOOK_URL"
    )

    if [ "$http_code" = "204" ]; then
        discord_log "Mensagem enviada"
        return 0

    else
        discord_log \
        "Falha envio HTTP $http_code"

        return 1
    fi
}

# -------------------------------------------------------------
# Enviar Embed Discord
# -------------------------------------------------------------
send_embed()
{
    local json="$1"

    if [ -z "$json" ]; then
        discord_log "Embed vazio"
        return 1
    fi

    http_code=$(curl \
        -s \
        -o /tmp/dsm_discord_response \
        -w "%{http_code}" \
        -H "Content-Type: application/json" \
        -X POST \
        -d "$json" \
        "$DISCORD_WEBHOOK_URL"
    )

    if [ "$http_code" = "204" ]; then
        discord_log "Embed enviado"
        return 0

    else
        discord_log \
        "Falha embed HTTP $http_code"

        return 1
    fi
}

# -------------------------------------------------------------
# Teste rápido
# -------------------------------------------------------------
send_test()
{

send_message "

🟢 **DSM Discord Integration Test**

Servidor:
$(hostname)

Status:
Webhook funcionando

Hora:
$(date '+%d/%m/%Y %H:%M:%S')

"
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
prepare_log
load_config

case "$1" in

message)
    send_message "$2"
;;

embed)
    send_embed "$2"
;;

test)
    send_test
;;

*)
cat <<EOF


DSM Discord Webhook v1.2.0


Uso:


Mensagem simples:

 discord_webhook.sh message "texto"



Embed:

 discord_webhook.sh embed '{"embeds":[]}'



Teste:

 discord_webhook.sh test



EOF
;;
esac
