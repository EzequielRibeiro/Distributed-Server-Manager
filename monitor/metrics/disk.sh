#!/bin/bash
# =============================================================
# monitor/metrics/disk.sh - DSM Metrics Engine v1.1.0
# Coleta:
#   - Espaço total do disco
#   - Espaço usado
#   - Espaço livre
#   - Percentual livre
#   - Percentual usado
#   - Diretório do servidor DayZ
# =============================================================

LOG_MODULE="metrics-disk"

# =============================================================
# Diretório monitorado
# Normalmente: /home/dayzserver/serverfiles
# Obtido pela configuração DSM/LGSM
# =============================================================
metrics_disk_path()
{
    if [ -n "$LGSM_HOME" ]; then
        echo "$LGSM_HOME"
        return
    fi

    if [ -n "$INSTANCE_DIR" ]; then
        echo "$INSTANCE_DIR"
        return
    fi
    echo "/"
}

# =============================================================
# Espaço total em GB
# =============================================================
metrics_disk_total_gb()
{
    local path
    path="$(metrics_disk_path)"

    df -BG "$path" 2>/dev/null |
    awk 'NR==2 {
        gsub("G","",$2);
        print $2
    }'
}

# =============================================================
# Espaço usado em GB
# =============================================================
metrics_disk_used_gb()
{
    local path
    path="$(metrics_disk_path)"

    df -BG "$path" 2>/dev/null |
    awk 'NR==2 {
        gsub("G","",$3);
        print $3
    }'
}

# =============================================================
# Espaço livre em GB
# =============================================================
metrics_disk_free_gb()
{
    local path
    path="$(metrics_disk_path)"

    df -BG "$path" 2>/dev/null |
    awk 'NR==2 {
        gsub("G","",$4);
        print $4
    }'
}

# =============================================================
# Percentual utilizado
# =============================================================
metrics_disk_used_pct()
{
    local path
    path="$(metrics_disk_path)"

    df "$path" 2>/dev/null |
    awk 'NR==2 {
        gsub("%","");
        print $5
    }'
}

# =============================================================
# Percentual livre
# =============================================================
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

# =============================================================
# Espaço livre formatado
# =============================================================
metrics_disk_free_human()
{
    local path
    path="$(metrics_disk_path)"

    df -h "$path" 2>/dev/null |
    awk 'NR==2 {print $4}'
}

# =============================================================
# JSON do módulo Disk
# =============================================================
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
