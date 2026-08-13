#!/bin/bash
# =============================================================
# monitor/metrics/cpu.sh - DSM Metrics Engine v1.1.0
# Coleta:
#   - CPU do processo DayZ
#   - CPU total do host
#   - Número de CPUs disponíveis
# =============================================================

LOG_MODULE="metrics-cpu"

# =============================================================
# CPU do processo DayZ
# Usa o PID gerenciado pelo DSM
# =============================================================
metrics_cpu_process_pct()
{
    local pid
    pid="$(pid_get 2>/dev/null)"

    if [ -z "$pid" ]; then
        echo "0"
        return
    fi

    ps \
      -p "$pid" \
      -o %cpu= \
      2>/dev/null \
      | awk '{printf "%.1f", $1}'
}

# =============================================================
# CPU total do host
# Calculada usando /proc/stat
# =============================================================
metrics_cpu_host_pct()
{
    local cpu1 cpu2

    cpu1=$(awk '/^cpu / {
        total=$2+$3+$4+$5+$6+$7+$8+$9+$10+$11
        idle=$5+$6
        print total,idle
        exit
    }' /proc/stat)


    sleep 1


    cpu2=$(awk '/^cpu / {
        total=$2+$3+$4+$5+$6+$7+$8+$9+$10+$11
        idle=$5+$6
        print total,idle
        exit
    }' /proc/stat)


    local total1 idle1 total2 idle2

    read total1 idle1 <<< "$cpu1"
    read total2 idle2 <<< "$cpu2"


    local total_diff=$((total2-total1))
    local idle_diff=$((idle2-idle1))


    if [ "$total_diff" -le 0 ]
    then
        echo "0"
        return
    fi


    awk -v total="$total_diff" \
        -v idle="$idle_diff" '
    BEGIN {
        printf "%.1f", ((total-idle)/total)*100
    }'
}

# =============================================================
# Quantidade de CPUs
# =============================================================
metrics_cpu_count()
{
    nproc 2>/dev/null || echo 1
}

# =============================================================
# JSON do módulo CPU
# =============================================================
metrics_cpu_json()
{
cat <<EOF
{
    "process_pct": "$(metrics_cpu_process_pct)",
    "host_pct": "$(metrics_cpu_host_pct)",
    "cores": "$(metrics_cpu_count)"
}
EOF
}
