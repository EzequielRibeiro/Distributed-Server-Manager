#!/bin/bash
# =============================================================
# DSM Restart Jobs
#
# Arquivo:
#   scheduler/restart_jobs.sh
#
# Responsável:
#   Reinicialização automática do servidor DayZ
#
# DSM Scheduler v1.2.0
#
# Atualização:
#   - Lock contra restart duplicado
#   - Eventos DSM
#   - Validação de falhas
#   - Proteção de limpeza
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

LOG_FILE="${DSM_ROOT}/logs/restart.log"
DSM_CMD="${DSM_CMD:-dsm}"
RESTART_DELAY="${RESTART_DELAY:-60}"
RESTART_LOCK="${DSM_ROOT}/cache/restart.lock"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
restart_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"

    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
    >> "$LOG_FILE"
}

# -------------------------------------------------------------
# Lock
# -------------------------------------------------------------
restart_lock()
{
    mkdir -p "$(dirname "$RESTART_LOCK")"

    if ! mkdir "$RESTART_LOCK" 2>/dev/null
    then
        restart_log \
        "Restart bloqueado: já existe uma execução"
        return 1
    fi

    echo "$$" > "$RESTART_LOCK/pid"
    return 0
}

restart_unlock()
{
    rm -rf "$RESTART_LOCK"
}

restart_cleanup()
{
    restart_unlock
}

trap restart_cleanup EXIT INT TERM

# -------------------------------------------------------------
# Eventos DSM
# -------------------------------------------------------------
restart_event()
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
restart_notify()
{
    local MESSAGE="$1"

    if declare -f notify_dispatch >/dev/null
    then
        notify_dispatch \
        "server_restart" \
        "{\"message\":\"$MESSAGE\"}"
    fi

    restart_log "$MESSAGE"
}

# -------------------------------------------------------------
# Status servidor
# -------------------------------------------------------------
server_status()
{
    $DSM_CMD status >/dev/null 2>&1
    return $?
}

# -------------------------------------------------------------
# Parar servidor
# -------------------------------------------------------------
stop_server()
{
    restart_log \
    "Parando servidor"

    restart_notify \
    "🔄 DSM: servidor será reiniciado"

    $DSM_CMD stop

    local rc=$?

    if [ "$rc" -eq 0 ]
    then
        restart_log \
        "Servidor parado"

        restart_event \
        "server.stopped" \
        "Servidor parado para restart"

        return 0
    fi

    restart_log \
    "Falha ao parar servidor (rc=$rc)"

    return 1
}

# -------------------------------------------------------------
# Iniciar servidor
# -------------------------------------------------------------
start_server()
{
    restart_log \
    "Iniciando servidor"

    $DSM_CMD start

    local rc=$?

    if [ "$rc" -eq 0 ]
    then
        restart_log \
        "Servidor iniciado"

        restart_event \
        "server.started" \
        "Servidor iniciado após restart"

        return 0
    fi

    restart_log \
    "Falha ao iniciar servidor (rc=$rc)"

    return 1
}

# -------------------------------------------------------------
# Restart completo
# -------------------------------------------------------------
restart_run()
{
    restart_lock || return 1

    restart_log \
    "=== Inicio restart automático ==="

    if server_status
    then
        stop_server || return 1
    else
        restart_log \
        "Servidor já estava parado"
    fi

    restart_log \
    "Aguardando ${RESTART_DELAY}s antes de iniciar"

    sleep "$RESTART_DELAY"

    if ! start_server
    then
        restart_notify \
        "❌ DSM: falha ao iniciar servidor após restart"

        restart_event \
        "server.restart_failed" \
        "Falha no restart"

        return 1
    fi

    restart_notify \
    "✅ DSM: servidor reiniciado com sucesso"

    restart_event \
    "server.restarted" \
    "Restart concluído"

    restart_log \
    "=== Restart concluído ==="

    return 0
}

# -------------------------------------------------------------
# Restart forçado
# -------------------------------------------------------------
force_restart()
{
    restart_lock || return 1

    restart_log \
    "Restart forçado iniciado"

    $DSM_CMD stop

    sleep 10

    $DSM_CMD start

    local rc=$?

    if [ "$rc" -eq 0 ]
    then
        restart_notify \
        "⚠️ DSM: restart forçado concluído"
    else
        restart_notify \
        "❌ DSM: falha no restart forçado"
    fi

    return "$rc"
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
case "$1" in
run)
restart_run
;;
force)
force_restart
;;
status)
server_status
;;
*)
cat <<EOF
DSM Restart Jobs

Uso:
restart_jobs.sh run
restart_jobs.sh force
restart_jobs.sh status
EOF
;;
esac
