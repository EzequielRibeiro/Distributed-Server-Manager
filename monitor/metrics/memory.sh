#!/bin/bash
# =============================================================
# monitor/metrics/memory.sh - DSM Metrics Engine v1.1.0
# Coleta:
#   - RAM total do host
#   - RAM usada
#   - RAM disponível
#   - Percentual livre
#   - RAM consumida pelo processo DayZ
# =============================================================

LOG_MODULE="metrics-memory"

# =============================================================
# RAM total do host em MB
# =============================================================
metrics_memory_total_mb()
{
    free -m 2>/dev/null |
        awk '/Mem:/ {print $2}'
}

# =============================================================
# RAM usada do host em MB
# =============================================================
metrics_memory_used_mb()
{
    free -m 2>/dev/null |
        awk '/Mem:/ {print $3}'
}

# =============================================================
# RAM disponível do host em MB
# =============================================================
metrics_memory_available_mb()
{
    free -m 2>/dev/null |
        awk '/Mem:/ {print $7}'
}

# =============================================================
# Percentual de RAM livre
# Baseado em memória disponível real
# =============================================================
metrics_memory_free_pct()
{
    local total available
    total="$(metrics_memory_total_mb)"
    available="$(metrics_memory_available_mb)"

    if [ -z "$total" ] || [ "$total" -eq 0 ]; then
        echo "0"
        return
    fi

    echo "$available $total" |
    awk '
    {
        printf "%.1f",
        ($1/$2)*100
    }'
}

# =============================================================
# RAM usada pelo processo DayZ
# RSS real do processo
# =============================================================
metrics_memory_process_mb()
{
    local pid
    local rss


    pid=$(pgrep -f "./DayZServer" | tail -1)


    if [ -z "$pid" ]
    then
        echo "0"
        return
    fi


    rss=$(ps -p "$pid" -o rss= 2>/dev/null)


    if [ -z "$rss" ]
    then
        echo "0"
        return
    fi


    echo "$rss" |
    awk '
    {
        printf "%.1f",
        $1/1024
    }'
}

# =============================================================
# Percentual de RAM usada pelo processo DayZ
# =============================================================
metrics_memory_process_pct()
{
    local process total
    process="$(metrics_memory_process_mb)"
    total="$(metrics_memory_total_mb)"

    if [ -z "$total" ] || [ "$total" -eq 0 ]; then
        echo "0"
        return
    fi

    echo "$process $total" |
    awk '
    {
        printf "%.1f",
        ($1/$2)*100
    }'
}

# =============================================================
# JSON do módulo Memory
# =============================================================
metrics_memory_json()
{
cat <<EOF
{
    "total_mb": "$(metrics_memory_total_mb)",
    "used_mb": "$(metrics_memory_used_mb)",
    "available_mb": "$(metrics_memory_available_mb)",
    "free_pct": "$(metrics_memory_free_pct)",
    "dayz_mb": "$(metrics_memory_process_mb)",
    "dayz_pct": "$(metrics_memory_process_pct)"
}
EOF
}
