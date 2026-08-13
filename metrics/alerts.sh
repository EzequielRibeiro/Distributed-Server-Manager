#!/bin/bash
# =============================================================
# DSM Metrics Engine v1.2.0
#
# Arquivo:
#   metrics/alerts.sh
#
# Função:
#   Motor de regras de alertas do DSM
#
# Responsável por:
#   - analisar métricas coletadas
#   - gerar eventos de alerta
#   - classificar severidade
#
# Estados possíveis:
#   INFO
#   WARNING
#   CRITICAL
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# -------------------------------------------------------------
# Carrega configurações
# -------------------------------------------------------------

ALERT_CONFIG="$DSM_ROOT/config/alerts.conf"

if [ -f "$ALERT_CONFIG" ]; then
    source "$ALERT_CONFIG"
fi

# -------------------------------------------------------------
# Função auxiliar JSON
# -------------------------------------------------------------

_alert_json()
{
    local id="$1"
    local level="$2"
    local title="$3"
    local value="$4"
    local limit="$5"
    local message="$6"

cat <<EOF
{
"id":"$id",
"level":"$level",
"title":"$title",
"value":"$value",
"limit":"$limit",
"message":"$message",
"timestamp":"$(date -Iseconds)"
}
EOF
}

# -------------------------------------------------------------
# CPU HOST
# -------------------------------------------------------------

check_cpu_host()
{
    local cpu
    cpu="$(metrics_cpu_host_pct 2>/dev/null)"
    [ -z "$cpu" ] && return

    cpu=${cpu%.*}

    if [ "$cpu" -ge "${CPU_HOST_CRITICAL:-90}" ]; then
        _alert_json \
        "cpu-host" \
        "CRITICAL" \
        "CPU Host crítica" \
        "${cpu}%" \
        "${CPU_HOST_CRITICAL}%" \
        "Uso crítico do processador do servidor"
    elif [ "$cpu" -ge "${CPU_HOST_WARNING:-80}" ]; then
        _alert_json \
        "cpu-host" \
        "WARNING" \
        "CPU Host elevada" \
        "${cpu}%" \
        "${CPU_HOST_WARNING}%" \
        "Uso elevado do processador"
    fi
}

# -------------------------------------------------------------
# CPU PROCESSO DAYZ
# -------------------------------------------------------------

check_cpu_dayz()
{
    local cpu
    cpu="$(metrics_cpu_process_pct 2>/dev/null)"
    [ -z "$cpu" ] && return

    cpu=${cpu%.*}

    if [ "$cpu" -ge "${CPU_DAYZ_CRITICAL:-90}" ]; then
        _alert_json \
        "cpu-dayz" \
        "CRITICAL" \
        "CPU DayZ crítica" \
        "${cpu}%" \
        "${CPU_DAYZ_CRITICAL}%" \
        "Processo DayZ consumindo CPU excessivamente"
    elif [ "$cpu" -ge "${CPU_DAYZ_WARNING:-70}" ]; then
        _alert_json \
        "cpu-dayz" \
        "WARNING" \
        "CPU DayZ elevada" \
        "${cpu}%" \
        "${CPU_DAYZ_WARNING}%" \
        "Processo DayZ com alto consumo"
    fi
}

# -------------------------------------------------------------
# MEMÓRIA
# -------------------------------------------------------------

check_memory()
{
    local mem
    mem="$(metrics_memory_host_used_pct 2>/dev/null)"

    [ -z "$mem" ] && return

    mem=${mem%.*}

    if [ "$mem" -ge "${RAM_CRITICAL:-90}" ]; then
        _alert_json \
        "memory" \
        "CRITICAL" \
        "Memória crítica" \
        "${mem}%" \
        "${RAM_CRITICAL}%" \
        "Memória RAM quase esgotada"
    elif [ "$mem" -ge "${RAM_WARNING:-80}" ]; then
        _alert_json \
        "memory" \
        "WARNING" \
        "Memória elevada" \
        "${mem}%" \
        "${RAM_WARNING}%" \
        "Uso elevado de memória RAM"
    fi
}

# -------------------------------------------------------------
# DISCO
# -------------------------------------------------------------

check_disk()
{
    local disk
    disk="$(metrics_disk_free_pct 2>/dev/null)"

    [ -z "$disk" ] && return

    disk=${disk%.*}

    if [ "$disk" -le "${DISK_CRITICAL:-10}" ]; then
        _alert_json \
        "disk" \
        "CRITICAL" \
        "Disco crítico" \
        "${disk}% livre" \
        "${DISK_CRITICAL}% livre" \
        "Espaço em disco insuficiente"
    elif [ "$disk" -le "${DISK_WARNING:-20}" ]; then
        _alert_json \
        "disk" \
        "WARNING" \
        "Disco baixo" \
        "${disk}% livre" \
        "${DISK_WARNING}% livre" \
        "Pouco espaço disponível"
    fi
}

# -------------------------------------------------------------
# TEMPERATURA
# -------------------------------------------------------------

check_temperature()
{
    local temp
    temp="$(metrics_temperature_cpu 2>/dev/null)"
    [ -z "$temp" ] && return

    temp=${temp%.*}

    if [ "$temp" -ge "${TEMP_CRITICAL:-85}" ]; then
        _alert_json \
        "temperature" \
        "CRITICAL" \
        "Temperatura crítica" \
        "${temp}C" \
        "${TEMP_CRITICAL}C" \
        "Temperatura acima do limite"
    elif [ "$temp" -ge "${TEMP_WARNING:-70}" ]; then
        _alert_json \
        "temperature" \
        "WARNING" \
        "Temperatura elevada" \
        "${temp}C" \
        "${TEMP_WARNING}C" \
        "Servidor aquecendo"
    fi
}

# -------------------------------------------------------------
# SERVIDOR DAYZ
# -------------------------------------------------------------

check_server()
{
    if ! pid_is_running; then
        _alert_json \
        "server-offline" \
        "CRITICAL" \
        "Servidor offline" \
        "OFFLINE" \
        "ONLINE" \
        "Servidor DayZ não está executando"
    fi
}

# -------------------------------------------------------------
# GERA JSON FINAL
# -------------------------------------------------------------

alerts_json()
{
    local first=1

    echo "["

    for alert in \
        "$(check_server)" \
        "$(check_cpu_host)" \
        "$(check_cpu_dayz)" \
        "$(check_memory)" \
        "$(check_disk)" \
        "$(check_temperature)"
    do
        [ -z "$alert" ] && continue

        if [ $first -eq 0 ]; then
            echo ","
        fi

        first=0
        echo "$alert"
    done

    echo "]"
}

# execução direta
if [ "${1}" = "json" ]; then
    alerts_json
fi
