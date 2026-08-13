#!/bin/bash
# =============================================================
# DSM Backup Jobs
#
# Arquivo:
#   scheduler/backup_jobs.sh
#
# Integração Scheduler -> Módulo Backup DSM
#
# DSM Version:
#   1.2.0
# =============================================================

: "${DSM_ROOT:=/opt/dsm}"

BACKUP_MODULE="${DSM_ROOT}/backup/backup.sh"

LOG_MODULE="backup"

# =============================================================
# Carregar módulo Backup
# =============================================================

if [ -f "$BACKUP_MODULE" ]
then
    source "$BACKUP_MODULE"
else
    echo "Erro: módulo Backup não encontrado: $BACKUP_MODULE"
    exit 1
fi

# =============================================================
# Log
# =============================================================

backup_job_log()
{
    log_info "[scheduler] $1"
}

# =============================================================
# Backup completo DSM
# =============================================================

backup_run()
{
    backup_job_log "Backup automático iniciado"

    if declare -f snapshot_create >/dev/null
    then
        snapshot_create "scheduled_backup"
    fi

    local FILE

    FILE=$(create_run)

    if [ $? -ne 0 ]
    then
        backup_job_log "Falha na criação do backup"

        events_emit \
        "backup.failed" \
        "Falha ao criar backup automático"

        notify_dispatch \
        "backup_failed" \
        '{"source":"scheduler"}'

        return 1
    fi

    backup_job_log \
    "Backup criado: $(basename "$FILE")"

    if declare -f checksum_generate >/dev/null
    then
        checksum_generate "$FILE"
    fi

    if declare -f rotate_run >/dev/null
    then
        rotate_run
    fi

    events_emit \
    "backup.created" \
    "$(basename "$FILE")"

    notify_dispatch \
    "backup_created" \
    "{\"file\":\"$(basename "$FILE")\"}"

    backup_job_log "Backup automático concluído"

    return 0
}

# =============================================================
# Backup manual DayZ
# Compatibilidade
# =============================================================

backup_dayz()
{
    backup_run
}

# =============================================================
# Backup DSM
# Compatibilidade
# =============================================================

backup_dsm()
{
    backup_run
}

# =============================================================
# Limpeza
# =============================================================

cleanup_old_backups()
{
    if declare -f rotate_run >/dev/null
    then
        rotate_run
    else
        log_warn "Rotação de backup não disponível"
    fi
}

# =============================================================
# CLI
# =============================================================

case "$1" in
run)
backup_run
;;
dayz)
backup_dayz
;;
dsm)
backup_dsm
;;
cleanup)
cleanup_old_backups
;;
*)
cat <<EOF
DSM Backup Jobs

Uso:
backup_jobs.sh run
backup_jobs.sh dayz
backup_jobs.sh dsm
backup_jobs.sh cleanup
EOF
;;
esac
