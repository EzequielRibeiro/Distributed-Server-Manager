#!/bin/bash
# =============================================================
# metrics/alerts.sh
# DSM Metrics Engine v1.1.0
# Gera lista de alertas ativos em formato JSON
# =============================================================

LOG_MODULE="metrics"

# ------------------------------------------------------------------
# Limites (podem futuramente vir de metrics.conf)
# ------------------------------------------------------------------
CPU_HOST_WARN=80
CPU_HOST_CRIT=90
CPU_DAYZ_WARN=70
CPU_DAYZ_CRIT=90
RAM_HOST_WARN=80
RAM_HOST_CRIT=90
DISK_WARN=20
DISK_CRIT=10
TEMP_WARN=70
TEMP_CRIT=85
LOAD_WARN_FACTOR=1
LOAD_CRIT_FACTOR=2

# ------------------------------------------------------------------
_alert_begin() {
    echo "["
    ALERT_FIRST=1
}

_alert_end() {
    echo "]"
}

_alert_add() {
    local id="$1"
    local level="$2"
    local title="$3"
    local value="$4"
    local threshold="$5"
    local message="$6"

    [ "$ALERT_FIRST" -eq 0 ] && echo ","

    ALERT_FIRST=0

    cat <<EOF
{
  "id":"$id",
  "level":"$level",
  "title":"$title",
  "value":"$value",
  "threshold":"$threshold",
  "message":"$message",
  "timestamp":"$(date -Iseconds)"
}
EOF
}

# =============================================================
# CPU HOST
# =============================================================
alerts_cpu_host() {
    local cpu
    cpu="$(metrics_cpu_host_pct)"
    cpu="${cpu%.*}"
    [ -z "$cpu" ] && cpu=0

    if [ "$cpu" -ge "$CPU_HOST_CRIT" ]; then
        _alert_add \
            cpu-host \
            CRITICAL \
            "CPU Host elevada" \
            "${cpu}%" \
            "${CPU_HOST_CRIT}%" \
            "Uso crítico da CPU do host."
    elif [ "$cpu" -ge "$CPU_HOST_WARN" ]; then
        _alert_add \
            cpu-host \
            WARNING \
            "CPU Host elevada" \
            "${cpu}%" \
            "${CPU_HOST_WARN}%" \
            "Uso elevado da CPU do host."
    fi
}

# =============================================================
# CPU DAYZ
# =============================================================
alerts_cpu_dayz() {
    local cpu
    cpu="$(metrics_cpu_process_pct)"
    cpu="${cpu%.*}"
    [ -z "$cpu" ] && cpu=0

    if [ "$cpu" -ge "$CPU_DAYZ_CRIT" ]; then
        _alert_add \
            cpu-dayz \
            CRITICAL \
            "CPU DayZ crítica" \
            "${cpu}%" \
            "${CPU_DAYZ_CRIT}%" \
            "Uso crítico do processo DayZ."
    elif [ "$cpu" -ge "$CPU_DAYZ_WARN" ]; then
        _alert_add \
            cpu-dayz \
            WARNING \
            "CPU DayZ elevada" \
            "${cpu}%" \
            "${CPU_DAYZ_WARN}%" \
            "Uso elevado do processo DayZ."
    fi
}

# =============================================================
# RAM HOST
# =============================================================
alerts_ram_host() {
    local used
    used="$(metrics_memory_host_used_pct)"
    used="${used%.*}"
    [ -z "$used" ] && used=0

    if [ "$used" -ge "$RAM_HOST_CRIT" ]; then
        _alert_add \
            ram-host \
            CRITICAL \
            "RAM do host crítica" \
            "${used}%" \
            "${RAM_HOST_CRIT}%" \
            "Pouca memória livre."
    elif [ "$used" -ge "$RAM_HOST_WARN" ]; then
        _alert_add \
            ram-host \
            WARNING \
            "RAM do host elevada" \
            "${used}%" \
            "${RAM_HOST_WARN}%" \
            "Uso elevado de memória."
    fi
}

# =============================================================
# DISCO
# =============================================================
alerts_disk() {
    local free
    free="$(metrics_disk_free_pct)"
    free="${free%.*}"
    [ -z "$free" ] && free=0

    if [ "$free" -le "$DISK_CRIT" ]; then
        _alert_add \
            disk \
            CRITICAL \
            "Espaço em disco crítico" \
            "${free}% livre" \
            "${DISK_CRIT}% livre" \
            "Disco praticamente cheio."
    elif [ "$free" -le "$DISK_WARN" ]; then
        _alert_add \
            disk \
            WARNING \
            "Espaço em disco baixo" \
            "${free}% livre" \
            "${DISK_WARN}% livre" \
            "Pouco espaço disponível."
    fi
}

# =============================================================
# TEMPERATURA
# =============================================================
alerts_temperature() {
    local temp
    temp="$(metrics_temperature_cpu)"
    temp="${temp%.*}"
    [ -z "$temp" ] && return

    if [ "$temp" -ge "$TEMP_CRIT" ]; then
        _alert_add \
            temperature \
            CRITICAL \
            "Temperatura crítica" \
            "${temp}°C" \
            "${TEMP_CRIT}°C" \
            "CPU supera temperatura segura."
    elif [ "$temp" -ge "$TEMP_WARN" ]; then
        _alert_add \
            temperature \
            WARNING \
            "Temperatura elevada" \
            "${temp}°C" \
            "${TEMP_WARN}°C" \
            "CPU aquecendo."
    fi
}

# =============================================================
# LOAD AVERAGE
# =============================================================
alerts_load() {
    local load
    local cpus
    load="$(metrics_load_1m)"
    cpus="$(nproc)"
    local warn=$((cpus * LOAD_WARN_FACTOR))
    local crit=$((cpus * LOAD_CRIT_FACTOR))
    load="${load%.*}"
    [ -z "$load" ] && return

    if [ "$load" -ge "$crit" ]; then
        _alert_add \
            load \
            CRITICAL \
            "Load Average crítico" \
            "$load" \
            "$crit" \
            "Carga excessiva no host."
    elif [ "$load" -ge "$warn" ]; then
        _alert_add \
            load \
            WARNING \
            "Load Average elevado" \
            "$load" \
            "$warn" \
            "Carga elevada."
    fi
}

# =============================================================
# STATUS DO SERVIDOR
# =============================================================
alerts_server() {
    if ! pid_is_running; then
        _alert_add \
            server \
            CRITICAL \
            "Servidor Offline" \
            "OFFLINE" \
            "ONLINE" \
            "Servidor DayZ não está em execução."
    fi
}

# =============================================================
# API
# =============================================================
alerts_json() {
    _alert_begin
    alerts_server
    alerts_cpu_host
    alerts_cpu_dayz
    alerts_ram_host
    alerts_disk
    alerts_temperature
    alerts_load
    _alert_end
}
