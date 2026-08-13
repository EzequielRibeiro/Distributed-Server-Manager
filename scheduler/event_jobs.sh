#!/bin/bash
# =============================================================
# DSM Event Jobs
#
# Arquivo:
#   scheduler/event_jobs.sh
#
# Responsável:
#   Execução de tarefas por eventos
#
# DSM Version:
#   1.2.0
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

LOG_FILE="${DSM_ROOT}/logs/events.log"

RESTART_MODULE="${DSM_ROOT}/scheduler/restart_jobs.sh"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
event_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"

    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
    >> "$LOG_FILE"
}

# -------------------------------------------------------------
# Alertas
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
# Recuperação servidor offline
# -------------------------------------------------------------
handle_server_offline()
{
    event_log \
    "Evento SERVER_OFFLINE recebido"

    notify \
    "⚠️ DSM: servidor DayZ offline detectado"

    if [ -x "$RESTART_MODULE" ]
    then
        "$RESTART_MODULE" run
    fi
}

# -------------------------------------------------------------
# Crash servidor
# -------------------------------------------------------------
handle_server_crash()
{
    event_log \
    "Evento SERVER_CRASH recebido"

    notify \
    "🚨 DSM: crash detectado, iniciando recuperação"

    if [ -x "$RESTART_MODULE" ]
    then
        "$RESTART_MODULE" run
    fi
}

# -------------------------------------------------------------
# Falha backup
# -------------------------------------------------------------
handle_backup_failed()
{
    event_log \
    "Falha de backup"

    notify \
    "❌ DSM: backup falhou"
}

# -------------------------------------------------------------
# Falha atualização
# -------------------------------------------------------------
handle_update_failed()
{
    event_log \
    "Falha atualização"

    notify \
    "❌ DSM: atualização falhou"
}

# -------------------------------------------------------------
# Pouco espaço
# -------------------------------------------------------------
handle_low_disk()
{
    event_log \
    "Espaço em disco baixo"

    notify \
    "⚠️ DSM: pouco espaço em disco"
}

# -------------------------------------------------------------
# Dispatcher
# -------------------------------------------------------------
event_dispatch()
{
    local EVENT="$1"

    case "$EVENT" in
    SERVER_OFFLINE)
        handle_server_offline
    ;;
    SERVER_CRASH)
        handle_server_crash
    ;;
    BACKUP_FAILED)
        handle_backup_failed
    ;;
    UPDATE_FAILED)
        handle_update_failed
    ;;
    LOW_DISK_SPACE)
        handle_low_disk
    ;;
    *)
        event_log \
        "Evento desconhecido: $EVENT"
        return 1
    ;;
    esac
}

# -------------------------------------------------------------
# Executar comando manual
# -------------------------------------------------------------
event_command()
{
    local CMD="$1"

    event_log \
    "Executando comando evento: $CMD"

    eval "$CMD"
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
case "$1" in
trigger)
event_dispatch "$2"
;;
command)
event_command "$2"
;;
*)
cat <<EOF
DSM Event Jobs

Uso:
event_jobs.sh trigger EVENTO

Exemplos:
event_jobs.sh trigger SERVER_OFFLINE
event_jobs.sh trigger SERVER_CRASH
EOF
;;
esac
