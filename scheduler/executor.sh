#!/bin/bash
# =============================================================
# DSM Scheduler Executor
#
# Arquivo:
#   scheduler/executor.sh
#
# Responsável:
#   Executar comandos dos jobs
#
# DSM Version:
#   1.2.2
#
# Correções:
#   - Lock por job
#   - Integração history
#   - Execução lock_run
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

SCHEDULER_DIR="${DSM_ROOT}/scheduler"
CACHE_DIR="${DSM_ROOT}/cache"
LOG_FILE="${DSM_ROOT}/logs/executor.log"

source "${SCHEDULER_DIR}/history.sh"

# -------------------------------------------------------------
# Lock por job
# -------------------------------------------------------------
executor_lock()
{
    local JOB="$1"

    mkdir -p "$CACHE_DIR"

    local LOCK="${CACHE_DIR}/scheduler_${JOB}.lock"

    if [ -e "${LOCK}.d" ]
    then
        return 1
    fi

    mkdir "${LOCK}.d" 2>/dev/null
}

executor_unlock()
{
    local JOB="$1"

    rm -rf \
    "${CACHE_DIR}/scheduler_${JOB}.lock.d"
}

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
executor_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"

    echo \
"$(date '+%Y-%m-%d %H:%M:%S') - $1" \
>> "$LOG_FILE"
}

# -------------------------------------------------------------
# Executar módulo DSM
#
# Formato:
#
# lock_run modulo função argumentos
#
# Ex:
# lock_run backup backup_run
#
# -------------------------------------------------------------
executor_lock_run()
{
    local MODULE="$1"
    shift

    local COMMAND="$@"

    local SCRIPT="${DSM_ROOT}/${MODULE}.sh"

    case "$MODULE" in
        backup)
            SCRIPT="${DSM_ROOT}/scheduler/backup_jobs.sh"
        ;;
        doctor)
            SCRIPT="${DSM_ROOT}/doctor/instance_runner.sh"
        ;;
        mods_update)
            SCRIPT="${DSM_ROOT}/mods/updater.sh"
        ;;
        restart)
            SCRIPT="${DSM_ROOT}/scheduler/restart_jobs.sh"
        ;;
        *)
            ;;
    esac

    if [ ! -x "$SCRIPT" ] &&
       [ ! -f "$SCRIPT" ]
    then
        executor_log \
        "Módulo não encontrado: $MODULE"
        return 1
    fi

    "$SCRIPT" $COMMAND
}

# -------------------------------------------------------------
# Execução principal
#
# Uso:
#
# executor_run JOB COMMAND
#
# -------------------------------------------------------------
executor_run()
{
    local JOB="$1"
    shift

    local COMMAND="$@"

    if ! executor_lock "$JOB"
    then
        executor_log \
        "Job bloqueado: $JOB"
        return 2
    fi

    local START
    START=$(date +%s)

    executor_log \
    "Iniciando job: $JOB"

    local RC=0

    case "$COMMAND" in

        backup)
            "${DSM_ROOT}/scheduler/backup_jobs.sh" run
            RC=$?
        ;;

        doctor)
            #
            # Doctor universal multi-instância.
            #
            # Descobre as instâncias existentes e executa os
            # adapters específicos de cada jogo.
            #
            "${DSM_ROOT}/doctor/instance_runner.sh"
            RC=$?
        ;;

        mods_update)
            #
            # Atualizador legado DayZ.
            # Mantido por compatibilidade, mas o job automático
            # deve permanecer desabilitado até ser instance-aware.
            #
            "${DSM_ROOT}/mods/updater.sh"
            RC=$?
        ;;

        restart)
            "${DSM_ROOT}/scheduler/restart_jobs.sh" run
            RC=$?
        ;;

        lock_run*)
            local DATA
            DATA="${COMMAND#lock_run }"
            executor_lock_run $DATA
            RC=$?
        ;;

        *)
            bash -c "$COMMAND"
            RC=$?
        ;;

    esac

    local END
    END=$(date +%s)

    local DURATION
    DURATION=$((END-START))

    executor_unlock "$JOB"

    history_record \
    "$JOB" \
    "$RC" \
    "$DURATION"

    if [ "$RC" -eq 0 ]
    then
        executor_log \
        "Job concluído: $JOB (${DURATION}s)"
    else
        executor_log \
        "Job falhou: $JOB rc=$RC"
    fi

    return "$RC"
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
case "$1" in
run)
executor_run \
"$2" \
"${@:3}"
;;
lock_run)
executor_lock_run \
"${@:2}"
;;
*)
cat <<EOF
DSM Scheduler Executor

Uso:
executor.sh run JOB COMMAND
executor.sh lock_run MODULO FUNÇÃO

Exemplo:
executor.sh run backup "lock_run backup backup_run"
EOF
;;
esac
fi
