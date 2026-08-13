#!/bin/bash
# =============================================================
# monitor/metrics/system.sh - DSM Metrics Engine v1.1.0
# Coleta:
#   - Load Average 1/5/15 minutos
#   - Uptime do host
#   - Hostname
#   - Kernel
#   - Distribuição Linux
#   - Número de processos
#   - Processos DayZ
# =============================================================

LOG_MODULE="metrics-system"

# =============================================================
# Load Average
# =============================================================
metrics_system_load()
{
    awk '
    {
        print $1,$2,$3
    }' /proc/loadavg 2>/dev/null
}

metrics_system_load_1m()
{
    metrics_system_load | awk '{print $1}'
}

metrics_system_load_5m()
{
    metrics_system_load | awk '{print $2}'
}

metrics_system_load_15m()
{
    metrics_system_load | awk '{print $3}'
}

# =============================================================
# Uptime do host
# =============================================================
metrics_system_uptime_seconds()
{
    awk '{print int($1)}' /proc/uptime 2>/dev/null
}

metrics_system_uptime_format()
{
    local seconds
    seconds="$(metrics_system_uptime_seconds)"

    if [ -z "$seconds" ]; then
        echo "N/D"
        return
    fi

    local days hours minutes
    days=$((seconds / 86400))
    hours=$(( (seconds % 86400) / 3600 ))
    minutes=$(( (seconds % 3600) / 60 ))

    if [ "$days" -gt 0 ]; then
        echo "${days}d ${hours}h ${minutes}m"
    else
        echo "${hours}h ${minutes}m"
    fi
}

# =============================================================
# Hostname
# =============================================================
metrics_system_hostname()
{
    hostname 2>/dev/null || echo "unknown"
}

# =============================================================
# Kernel Linux
# =============================================================
metrics_system_kernel()
{
    uname -r 2>/dev/null || echo "unknown"
}

# =============================================================
# Distribuição Linux
# =============================================================
metrics_system_distribution()
{
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$PRETTY_NAME"
    else
        echo "unknown"
    fi
}

# =============================================================
# Quantidade total de processos
# =============================================================
metrics_system_process_count()
{
    ps -e --no-headers 2>/dev/null |
    wc -l
}

# =============================================================
# Processos DayZ
# Busca processos contendo: dayz, DayZServer, server_x64
# =============================================================
metrics_system_dayz_processes()
{
    ps aux 2>/dev/null |
    grep -Ei \
    'dayz|dayzserver|server_x64' |
    grep -v grep |
    wc -l
}

# =============================================================
# JSON do módulo System
# =============================================================
metrics_system_json()
{
cat <<EOF
{
    "hostname": "$(metrics_system_hostname)",
    "kernel": "$(metrics_system_kernel)",
    "distribution": "$(metrics_system_distribution)",
    "load_average": {
        "1m": "$(metrics_system_load_1m)",
        "5m": "$(metrics_system_load_5m)",
        "15m": "$(metrics_system_load_15m)"
    },
    "uptime_seconds": "$(metrics_system_uptime_seconds)",
    "uptime": "$(metrics_system_uptime_format)",
    "processes": "$(metrics_system_process_count)",
    "dayz_processes": "$(metrics_system_dayz_processes)"
}
EOF
}
