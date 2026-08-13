#!/bin/bash
# =============================================================
# DSM Steam Update Jobs
#
# Arquivo:
#   scheduler/steam_jobs.sh
#
# Responsável:
#   Atualização SteamCMD / DayZ Server
#
# DSM Scheduler v1.2.0
#
# Atualização:
#   - Lock contra atualização simultânea
#   - Eventos DSM
#   - Notificações centralizadas
#   - Proteção pré-update
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

STEAMCMD_DIR="${STEAMCMD_DIR:-${DSM_ROOT}/steamcmd}"
STEAMCMD="${STEAMCMD_DIR}/steamcmd.sh"

SERVER_DIR="${LGSM_DIR:-${DSM_ROOT}/serverfiles}"
BACKUP_DIR="${DSM_ROOT}/backups/server"
LOG_FILE="${DSM_ROOT}/logs/steam_update.log"
STEAM_LOCK="${DSM_ROOT}/cache/steam_update.lock"

STEAM_USER="${STEAM_USER:-anonymous}"
DAYZ_APP_ID="221100"

BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
steam_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"

    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
    >> "$LOG_FILE"
}

# -------------------------------------------------------------
# Lock
# -------------------------------------------------------------
steam_lock()
{
    mkdir -p "$(dirname "$STEAM_LOCK")"

    if ! mkdir "$STEAM_LOCK" 2>/dev/null
    then
        steam_log \
        "Atualização Steam bloqueada: execução existente"
        return 1
    fi

    echo "$$" > "$STEAM_LOCK/pid"
    return 0
}

steam_unlock()
{
    rm -rf "$STEAM_LOCK"
}

trap steam_unlock EXIT INT TERM

# -------------------------------------------------------------
# Eventos DSM
# -------------------------------------------------------------
steam_event()
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
# Notificação DSM
# -------------------------------------------------------------
steam_notify()
{
    local MESSAGE="$1"

    if declare -f notify_dispatch >/dev/null
    then
        notify_dispatch \
        "steam_update" \
        "{\"message\":\"$MESSAGE\"}"
    fi

    steam_log "$MESSAGE"
}

# -------------------------------------------------------------
# Verificar SteamCMD
# -------------------------------------------------------------
check_steamcmd()
{
    if [ ! -x "$STEAMCMD" ]
    then
        steam_log \
        "SteamCMD não encontrado: $STEAMCMD"
        return 1
    fi
    return 0
}

# -------------------------------------------------------------
# Backup servidor
# -------------------------------------------------------------
backup_server()
{
    local DATE
    DATE=$(date '+%Y-%m-%d_%H%M%S')

    mkdir -p "$BACKUP_DIR"

    if [ ! -d "$SERVER_DIR" ]
    then
        steam_log \
        "Servidor não encontrado: $SERVER_DIR"
        return 1
    fi

    tar \
    -czf \
    "${BACKUP_DIR}/server_${DATE}.tar.gz" \
    "$SERVER_DIR"

    if [ $? -eq 0 ]
    then
        steam_log \
        "Backup criado"
        return 0
    fi

    steam_log \
    "Falha ao criar backup"
    return 1
}

# -------------------------------------------------------------
# Atualizar SteamCMD
# -------------------------------------------------------------
update_steamcmd()
{
    steam_log \
    "Atualizando SteamCMD"

    "$STEAMCMD" \
    +quit

    local rc=$?

    if [ "$rc" -eq 0 ]
    then
        steam_log \
        "SteamCMD atualizado"
        return 0
    fi

    steam_log \
    "Falha SteamCMD rc=$rc"
    return 1
}

# -------------------------------------------------------------
# Atualizar servidor DayZ
# -------------------------------------------------------------
update_server()
{
    steam_log \
    "Atualizando servidor DayZ"

    "$STEAMCMD" \
    +login "$STEAM_USER" \
    +force_install_dir "$SERVER_DIR" \
    +app_update "$DAYZ_APP_ID" validate \
    +quit

    local rc=$?

    if [ "$rc" -eq 0 ]
    then
        steam_log \
        "Servidor atualizado"

        steam_event \
        "server.updated" \
        "Servidor DayZ atualizado"

        return 0
    fi

    steam_log \
    "Falha atualização servidor rc=$rc"
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

    steam_log \
    "Backups antigos removidos"
}

# -------------------------------------------------------------
# Execução completa
# -------------------------------------------------------------
steam_run()
{
    steam_lock || return 1

    steam_notify \
    "🔄 DSM: iniciando atualização Steam/DayZ"

    steam_event \
    "steam.update_started" \
    "Atualização Steam iniciada"

    check_steamcmd

    if [ $? -ne 0 ]
    then
        steam_notify \
        "❌ DSM: SteamCMD não encontrado"
        return 1
    fi

    backup_server

    if [ $? -ne 0 ]
    then
        steam_notify \
        "❌ DSM: falha no backup antes do update"
        return 1
    fi

    update_steamcmd

    if [ $? -ne 0 ]
    then
        steam_notify \
        "❌ DSM: falha atualização SteamCMD"
        return 1
    fi

    update_server

    if [ $? -eq 0 ]
    then
        cleanup_backup
        steam_notify \
        "✅ DSM: servidor DayZ atualizado"

        steam_event \
        "steam.update_finished" \
        "Atualização concluída"

        return 0
    fi

    steam_notify \
    "❌ DSM: falha atualização DayZ"

    steam_event \
    "steam.update_failed" \
    "Falha na atualização"

    return 1
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
case "$1" in
run)
steam_run
;;
steamcmd)
update_steamcmd
;;
server)
update_server
;;
backup)
backup_server
;;
cleanup)
cleanup_backup
;;
*)
cat <<EOF
DSM Steam Jobs

Uso:
steam_jobs.sh run
steam_jobs.sh steamcmd
steam_jobs.sh server
steam_jobs.sh backup
steam_jobs.sh cleanup
EOF
;;
esac
