#!/bin/bash
# =============================================================
# DSM Mods Update Jobs
#
# Arquivo:
#   scheduler/mods_jobs.sh
#
# Responsável:
#   Atualização automática de Mods DayZ
#
# DSM Scheduler v1.2.0
#
# Atualização:
#   - Lock de atualização
#   - Integração mods/updater.sh
#   - Eventos DSM
#   - Rollback automático via módulo Mods
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

LOG_FILE="${DSM_ROOT}/logs/mods_update.log"
MODS_LOCK="${DSM_ROOT}/cache/mods_update.lock"
MODS_MODULE="${DSM_ROOT}/mods/updater.sh"

BACKUP_DIR="${DSM_ROOT}/backups/mods"

BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
mods_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"

    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
    >> "$LOG_FILE"
}

# -------------------------------------------------------------
# Lock
# -------------------------------------------------------------
mods_lock()
{
    mkdir -p "$(dirname "$MODS_LOCK")"

    if ! mkdir "$MODS_LOCK" 2>/dev/null
    then
        mods_log \
        "Atualização bloqueada: já existe outra execução"
        return 1
    fi

    echo "$$" > "$MODS_LOCK/pid"
    return 0
}

mods_unlock()
{
    rm -rf "$MODS_LOCK"
}

trap mods_unlock EXIT INT TERM

# -------------------------------------------------------------
# Eventos DSM
# -------------------------------------------------------------
mods_event()
{
    local EVENT="$1"
    local MESSAGE="$2"

    if declare -f events_emit >/dev/null
    then
        events_emit \
        "$EVENT" \
        "$MESSAGE"
    fi
}

# -------------------------------------------------------------
# Notificação
# -------------------------------------------------------------
mods_notify()
{
    local MESSAGE="$1"

    if declare -f notify_dispatch >/dev/null
    then
        notify_dispatch \
        "mods_update" \
        "{\"message\":\"$MESSAGE\"}"
    fi

    mods_log "$MESSAGE"
}

# -------------------------------------------------------------
# Backup manual dos Mods
#
# Usado somente como proteção extra
# O rollback oficial fica em mods/rollback.sh
# -------------------------------------------------------------
backup_mods()
{
    local DATE
    DATE=$(date '+%Y-%m-%d_%H%M%S')

    mkdir -p "$BACKUP_DIR"

    local MODS_PATH="${LGSM_DIR:-${DSM_ROOT}}/serverfiles/mods"

    if [ ! -d "$MODS_PATH" ]
    then
        mods_log \
        "Diretório de mods não encontrado: $MODS_PATH"
        return 1
    fi

    tar \
    -czf \
    "${BACKUP_DIR}/mods_${DATE}.tar.gz" \
    "$MODS_PATH"

    if [ $? -eq 0 ]
    then
        mods_log \
        "Backup dos mods criado"
        return 0
    fi

    mods_log \
    "Falha ao criar backup dos mods"
    return 1
}

# -------------------------------------------------------------
# Atualizar Mods
#
# Usa o módulo oficial:
#
# mods/updater.sh
#
# -------------------------------------------------------------
update_mods()
{
    mods_log \
    "Executando atualização DSM Mods"

    if [ ! -f "$MODS_MODULE" ]
    then
        mods_log \
        "Módulo updater.sh não encontrado"
        return 1
    fi

    source "$MODS_MODULE"

    if ! declare -f updater_run >/dev/null
    then
        mods_log \
        "Função updater_run não disponível"
        return 1
    fi

    updater_run --auto

    local rc=$?

    if [ "$rc" -eq 0 ]
    then
        mods_log \
        "Atualização de mods concluída"

        mods_event \
        "mods.updated" \
        "Atualização automática concluída"

        return 0
    fi

    mods_log \
    "Falha na atualização de mods"

    mods_event \
    "mods.update_failed" \
    "Falha na atualização automática"

    return 1
}

# -------------------------------------------------------------
# Limpeza backups
# -------------------------------------------------------------
cleanup_backup()
{
    [ -d "$BACKUP_DIR" ] || return 0

    find "$BACKUP_DIR" \
    -type f \
    -name "*.tar.gz" \
    -mtime +"$BACKUP_RETENTION_DAYS" \
    -delete

    mods_log \
    "Backups antigos removidos"
}

# -------------------------------------------------------------
# Execução principal
# -------------------------------------------------------------
mods_run()
{
    mods_lock || return 1

    mods_notify \
    "🔄 DSM: iniciando atualização dos Mods"

    mods_log \
    "Processo iniciado"

    backup_mods

    if [ $? -ne 0 ]
    then
        mods_notify \
        "❌ DSM: falha no backup dos Mods"
        return 1
    fi

    update_mods

    local rc=$?

    cleanup_backup

    if [ "$rc" -eq 0 ]
    then
        mods_notify \
        "✅ DSM: Mods atualizados com sucesso"
        return 0
    fi

    mods_notify \
    "❌ DSM: erro ao atualizar Mods"

    return 1
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
case "$1" in
run)
mods_run
;;
backup)
backup_mods
;;
update)
update_mods
;;
cleanup)
cleanup_backup
;;
*)
cat <<EOF
DSM Mods Jobs

Uso:
mods_jobs.sh run
mods_jobs.sh backup
mods_jobs.sh update
mods_jobs.sh cleanup
EOF
;;
esac
