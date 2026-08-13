#!/bin/bash
# =============================================================
# DSM Alert Engine
# Responsável:
# - Ler estados DSM
# - Aplicar regras
# - Gerar alertas
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
ALERT_STATE="$STATE_DIR/alerts.state.json"
QUEUE_FILE="$DSM_ROOT/dashboard/notifications/notification_queue.json"
RULES_FILE="$DSM_ROOT/dashboard/alerts/alert_rules.conf"

# -------------------------------------------------------------
# Ambiente
# -------------------------------------------------------------
mkdir -p "$(dirname "$ALERT_STATE")"
mkdir -p "$(dirname "$QUEUE_FILE")"
source "$RULES_FILE"

# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
timestamp() {
    date +"%Y-%m-%dT%H:%M:%S"
}

create_alert() {
    local level="$1"
    local title="$2"
    local message="$3"

    jq \
    -n \
    --arg level "$level" \
    --arg title "$title" \
    --arg message "$message" \
    --arg time "$(timestamp)" \
    '
    {
        id: ("alert-" + ($time)),
        level: $level,
        title: $title,
        message: $message,
        timestamp: $time,
        acknowledged: false
    }
    '
}

# -------------------------------------------------------------
# Inicializar
# -------------------------------------------------------------
if [ ! -f "$ALERT_STATE" ]
then
    echo "[]" > "$ALERT_STATE"
fi

if [ ! -f "$QUEUE_FILE" ]
then
    echo "[]" > "$QUEUE_FILE"
fi

ALERTS="[]"

# -------------------------------------------------------------
# Ler métricas
# -------------------------------------------------------------
METRICS="$STATE_DIR/metrics.state.json"
if [ -f "$METRICS" ]
then
    CPU=$(jq '.cpu.host_pct // 0' "$METRICS")
    RAM=$(jq '.memory.host_used_pct // 0' "$METRICS")
    DISK=$(jq '.disk.used_pct // 0' "$METRICS")
    TEMP=$(jq '.temperature.cpu_celsius // 0' "$METRICS")

    # CPU
    if (( $(echo "$CPU >= $CPU_CRITICAL" | bc -l) ))
    then
        ALERTS=$(jq \
        --argjson a "$(create_alert CRITICAL 'CPU crítica' "CPU em ${CPU}%")" \
        '. + [$a]' \
        <<< "$ALERTS")
    elif (( $(echo "$CPU >= $CPU_WARNING" | bc -l) ))
    then
        ALERTS=$(jq \
        --argjson a "$(create_alert WARNING 'CPU elevada' "CPU em ${CPU}%")" \
        '. + [$a]' \
        <<< "$ALERTS")
    fi

    # RAM
    if (( $(echo "$RAM >= $RAM_CRITICAL" | bc -l) ))
    then
        ALERTS=$(jq \
        --argjson a "$(create_alert CRITICAL 'Memória crítica' "RAM em ${RAM}%")" \
        '. + [$a]' \
        <<< "$ALERTS")
    fi

    # Disco
    if (( $(echo "$DISK >= $DISK_CRITICAL" | bc -l) ))
    then
        ALERTS=$(jq \
        --argjson a "$(create_alert CRITICAL 'Disco cheio' "Uso de disco ${DISK}%")" \
        '. + [$a]' \
        <<< "$ALERTS")
    fi

    # Temperatura
    if (( $(echo "$TEMP >= $TEMP_CRITICAL" | bc -l) ))
    then
        ALERTS=$(jq \
        --argjson a "$(create_alert CRITICAL 'Temperatura alta' "CPU ${TEMP}°C")" \
        '. + [$a]' \
        <<< "$ALERTS")
    fi
fi

# -------------------------------------------------------------
# Servidor Offline
# -------------------------------------------------------------
SERVER_STATE="$STATE_DIR/server.state.json"
if [ -f "$SERVER_STATE" ]
then
    ONLINE=$(jq '.online // false' "$SERVER_STATE")
    if [ "$ONLINE" = "false" ]
    then
        ALERTS=$(jq \
        --argjson a "$(create_alert CRITICAL 'Servidor Offline' 'Servidor DayZ não está respondendo')" \
        '. + [$a]' \
        <<< "$ALERTS")
    fi
fi

# -------------------------------------------------------------
# Salvar alertas
# -------------------------------------------------------------
echo "$ALERTS" > "$ALERT_STATE"

# adicionar na fila
jq -s 'add' "$ALERT_STATE" "$QUEUE_FILE" > "${QUEUE_FILE}.tmp"
mv "${QUEUE_FILE}.tmp" "$QUEUE_FILE"

echo "Alert Engine executado."
