#!/bin/bash
# =============================================================
# monitor/metrics/disk.sh - DSM Metrics Engine
# Coleta métricas do filesystem usado pelo Capivara.
# =============================================================

LOG_MODULE="metrics-disk"

metrics_disk_path()
{
    if [ -n "${INSTANCE_DIR:-}" ] && [ -e "${INSTANCE_DIR}" ]; then
        echo "${INSTANCE_DIR}"
        return
    fi
    if [ -n "${DSM_DATA_DIR:-}" ] && [ -e "${DSM_DATA_DIR}" ]; then
        echo "${DSM_DATA_DIR}"
        return
    fi
    if [ -n "${DSM_ROOT:-}" ] && [ -e "${DSM_ROOT}" ]; then
        echo "${DSM_ROOT}"
        return
    fi
    echo "/"
}

metrics_disk_total_gb()
{
    df -BG "$(metrics_disk_path)" 2>/dev/null |
        awk 'NR==2 {gsub("G","",$2); print $2}'
}

metrics_disk_used_gb()
{
    df -BG "$(metrics_disk_path)" 2>/dev/null |
        awk 'NR==2 {gsub("G","",$3); print $3}'
}

metrics_disk_free_gb()
{
    df -BG "$(metrics_disk_path)" 2>/dev/null |
        awk 'NR==2 {gsub("G","",$4); print $4}'
}

metrics_disk_used_pct()
{
    df "$(metrics_disk_path)" 2>/dev/null |
        awk 'NR==2 {gsub("%",""); print $5}'
}

metrics_disk_free_pct()
{
    local used
    used="$(metrics_disk_used_pct)"
    if [ -z "$used" ]; then
        echo "0"
        return
    fi
    echo $((100-used))
}

metrics_disk_free_human()
{
    df -h "$(metrics_disk_path)" 2>/dev/null |
        awk 'NR==2 {print $4}'
}

metrics_disk_json()
{
cat <<EOF
{
    "path": "$(metrics_disk_path)",
    "total_gb": "$(metrics_disk_total_gb)",
    "used_gb": "$(metrics_disk_used_gb)",
    "free_gb": "$(metrics_disk_free_gb)",
    "used_pct": "$(metrics_disk_used_pct)",
    "free_pct": "$(metrics_disk_free_pct)",
    "free_human": "$(metrics_disk_free_human)"
}
EOF
}
