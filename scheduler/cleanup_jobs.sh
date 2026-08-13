#!/bin/bash
# =============================================================
# DSM Cleanup Jobs
#
# Arquivo:
#   scheduler/cleanup_jobs.sh
#
# Responsável:
#   Limpeza automática do ambiente DSM
#
# DSM Version:
#   1.2.0
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

LOG_DIR="${DSM_ROOT}/logs"
BACKUP_DIR="${DSM_ROOT}/backups"
CACHE_DIR="${DSM_ROOT}/cache"
TMP_DIR="${DSM_ROOT}/tmp"

LOG_FILE="${DSM_ROOT}/logs/cleanup.log"

# Retenção padrão
LOG_RETENTION="${DSM_LOG_RETENTION:-30}"
BACKUP_RETENTION="${DSM_BACKUP_RETENTION:-30}"
CACHE_RETENTION="${DSM_CACHE_RETENTION:-7}"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
cleanup_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"

    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
    >> "$LOG_FILE"
}

# -------------------------------------------------------------
# Notificação
# -------------------------------------------------------------
notify()
{
    local MSG="$1"

    if [ -x "${DSM_ROOT}/alerts/alerts.sh" ]
    then
        "${DSM_ROOT}/alerts/alerts.sh" \
        send \
        "$MSG"
    fi
}

# -------------------------------------------------------------
# Limpar logs
# -------------------------------------------------------------
cleanup_logs()
{
    cleanup_log \
    "Limpando logs antigos"

    find "$LOG_DIR" \
    -type f \
    -name "*.log" \
    -mtime +"$LOG_RETENTION" \
    -delete
}

# -------------------------------------------------------------
# Limpar backups
# -------------------------------------------------------------
cleanup_backups()
{
    cleanup_log \
    "Limpando backups antigos"

    find "$BACKUP_DIR" \
    -type f \
    -name "*.tar.gz" \
    -mtime +"$BACKUP_RETENTION" \
    -delete
}

# -------------------------------------------------------------
# Limpar cache
# -------------------------------------------------------------
cleanup_cache()
{
    cleanup_log \
    "Limpando cache antigo"

    find "$CACHE_DIR" \
    -type f \
    -mtime +"$CACHE_RETENTION" \
    -delete
}

# -------------------------------------------------------------
# Limpar temporários
# -------------------------------------------------------------
cleanup_tmp()
{
    cleanup_log \
    "Limpando arquivos temporários"

    if [ -d "$TMP_DIR" ]
    then
        rm -rf "${TMP_DIR:?}"/*
    fi
}

# -------------------------------------------------------------
# Estatística de disco
# -------------------------------------------------------------
disk_usage()
{
    df -h "$DSM_ROOT" | tail -1
}

# -------------------------------------------------------------
# Execução completa
# -------------------------------------------------------------
cleanup_run()
{
    cleanup_log \
    "Iniciando limpeza DSM"

    cleanup_logs
    cleanup_backups
    cleanup_cache
    cleanup_tmp

    local USAGE
    USAGE=$(disk_usage)

    cleanup_log \
    "Uso de disco: $USAGE"

    notify \
    "🧹 DSM: limpeza automática concluída"

    return 0
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
case "$1" in
run)
cleanup_run
;;
logs)
cleanup_logs
;;
backups)
cleanup_backups
;;
cache)
cleanup_cache
;;
tmp)
cleanup_tmp
;;
disk)
disk_usage
;;
*)
cat <<EOF
DSM Cleanup Jobs

Uso:
cleanup_jobs.sh run
cleanup_jobs.sh logs
cleanup_jobs.sh backups
cleanup_jobs.sh cache
cleanup_jobs.sh tmp
cleanup_jobs.sh disk
EOF
;;
esac
