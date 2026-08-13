#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
#
# Arquivo:
#   config/discord_config.sh
#
# Função:
#   Carregar e validar configuração Discord
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

SECRET_FILE="$DSM_ROOT/config/discord.secret"

# -------------------------------------------------------------
# Carregar segredo
# -------------------------------------------------------------
discord_load_secret()
{
    if [ ! -f "$SECRET_FILE" ]; then
        echo "[DSM] ERRO: discord.secret não encontrado"
        return 1
    fi

    source "$SECRET_FILE"

    return 0
}

# -------------------------------------------------------------
# Validar configuração
# -------------------------------------------------------------
discord_validate()
{
    if [ "$DISCORD_ENABLED" != "true" ]; then
        echo "[DSM] Discord desativado"
        return 1
    fi

    if [ -z "$DISCORD_WEBHOOK_URL" ]; then
        echo "[DSM] Webhook Discord não configurado"
        return 1
    fi

    if [[ "$DISCORD_WEBHOOK_URL" != https://discord.com/api/webhooks/* ]]; then
        echo "[DSM] Webhook inválido"
        return 1
    fi

    return 0
}

# -------------------------------------------------------------
# Configurações padrão
# -------------------------------------------------------------
discord_defaults()
{
    # Nome do bot
    : "${DISCORD_USERNAME:=DSM Alert Bot}"

    # Canal lógico
    : "${DISCORD_CHANNEL:=dayz-server-alerts}"

    # Ambiente
    : "${DSM_ENVIRONMENT:=production}"

    # Intervalo de relatório
    : "${DISCORD_REPORT_INTERVAL:=3600}"

    # Limite de fila
    : "${DISCORD_QUEUE_LIMIT:=100}"
}

# -------------------------------------------------------------
# Níveis permitidos
# -------------------------------------------------------------
discord_levels()
{
    export ALERT_LEVEL_CRITICAL=true
    export ALERT_LEVEL_WARNING=true
    export ALERT_LEVEL_RECOVERY=true
    export ALERT_LEVEL_INFO=true
}

# -------------------------------------------------------------
# Exportar ambiente
# -------------------------------------------------------------
discord_export()
{
export DISCORD_USERNAME
export DISCORD_CHANNEL
export DISCORD_WEBHOOK_URL
export DISCORD_REPORT_INTERVAL
export DISCORD_QUEUE_LIMIT
export DSM_ENVIRONMENT
}

# -------------------------------------------------------------
# Inicialização automática
# -------------------------------------------------------------
discord_init()
{
    discord_load_secret || return 1
    discord_defaults
    discord_validate || return 1
    discord_levels
    discord_export

    return 0
}

# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    if discord_init; then
        echo "[DSM] Discord configuration OK"
        echo ""
        echo "Bot:"
        echo "$DISCORD_USERNAME"
        echo "Canal:"
        echo "$DISCORD_CHANNEL"
        echo "Ambiente:"
        echo "$DSM_ENVIRONMENT"
    else
        echo "[DSM] Discord configuration FAILED"
        exit 1
    fi
fi
