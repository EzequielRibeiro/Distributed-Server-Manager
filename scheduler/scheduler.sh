#!/bin/bash
# =============================================================
# DSM Scheduler Engine
#
# Arquivo:
#   scheduler/scheduler.sh
#
# Responsável:
#   Motor principal do Scheduler DSM
#
# DSM Version:
#   1.2.2
#
# Correções:
#   - Integração executor
#   - Lock por job
#   - Suporte lock_run
#   - Carregamento .task
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
SCHEDULER_DIR="${DSM_ROOT}/scheduler"
TASK_DIR="${SCHEDULER_DIR}/tasks"

LOG_FILE="${DSM_ROOT}/logs/scheduler.log"

# -------------------------------------------------------------
# Módulos
# -------------------------------------------------------------
source "${SCHEDULER_DIR}/executor.sh"
source "${SCHEDULER_DIR}/history.sh"
source "${SCHEDULER_DIR}/cron_engine.sh"
source "${SCHEDULER_DIR}/jobs.sh"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
scheduler_log()
{
    mkdir -p "$(dirname "$LOG_FILE")"

    echo \
"$(date '+%Y-%m-%d %H:%M:%S') - $1" \
>> "$LOG_FILE"
}

# -------------------------------------------------------------
# Carregar arquivo .task
#
# Formato:
#
# NAME=""
# SCHEDULE=""
# COMMAND=""
# ENABLED=1
#
# -------------------------------------------------------------
scheduler_load_task()
{
    local FILE="$1"

    if [ ! -f "$FILE" ]
    then
        return 1
    fi

    unset NAME
    unset SCHEDULE
    unset COMMAND
    unset ENABLED

    source "$FILE"

    if [ -z "$NAME" ] ||
       [ -z "$SCHEDULE" ] ||
       [ -z "$COMMAND" ]
    then
        scheduler_log \
        "Task inválida: $FILE"
        return 1
    fi

    #
    # Importação idempotente.
    #
    # Jobs já registrados no banco não devem provocar erro
    # durante cada inicialização do Scheduler.
    #
    if jobs_exists "$NAME"
    then
        scheduler_log \
        "Job já registrado, mantendo configuração atual: $NAME"

        return 0
    fi

    jobs_add \
    "$NAME" \
    "$SCHEDULE" \
    "$COMMAND" \
    "${ENABLED:-0}" \
    "$FILE"
}

# -------------------------------------------------------------
# Importar tasks
# -------------------------------------------------------------
scheduler_import_tasks()
{
    mkdir -p "$TASK_DIR"

    for FILE in "$TASK_DIR"/*.task
    do
        [ -f "$FILE" ] || continue

        scheduler_load_task "$FILE"
    done
}

# -------------------------------------------------------------
# Executar job
# -------------------------------------------------------------
scheduler_execute_job()
{
    local NAME="$1"

    local DATA

    DATA=$(jobs_show "$NAME")

    if [ -z "$DATA" ]
    then
        scheduler_log \
        "Job inexistente: $NAME"
        return 1
    fi

    local ENABLED
    local COMMAND

    ENABLED=$(echo "$DATA" | jq -r '.enabled')
    COMMAND=$(echo "$DATA" | jq -r '.command')

    if [ "$ENABLED" != "1" ]
    then
        scheduler_log \
        "Job desabilitado: $NAME"
        return 0
    fi

    scheduler_log \
    "Executando job: $NAME"

    executor_run \
    "$NAME" \
    "$COMMAND"
}

# -------------------------------------------------------------
# Verificar jobs
# -------------------------------------------------------------
scheduler_check()
{
    jobs_init

    local NOW
    NOW=$(date +%s)

    jq -c '.jobs[]' "$JOBS_DB" |
    while read JOB
    do
        local NAME
        local SCHEDULE
        local ENABLED

        NAME=$(echo "$JOB" | jq -r '.name')
        SCHEDULE=$(echo "$JOB" | jq -r '.schedule')
        ENABLED=$(echo "$JOB" | jq -r '.enabled')

        if [ "$ENABLED" != "1" ]
        then
            continue
        fi

        if cron_match "$SCHEDULE"
        then
            scheduler_execute_job "$NAME"
        fi
    done
}

# -------------------------------------------------------------
# Loop principal
# -------------------------------------------------------------
scheduler_run()
{
    scheduler_log \
    "Scheduler iniciado"

    scheduler_import_tasks

    while true
    do
        scheduler_check
        sleep 60
    done
}

# -------------------------------------------------------------
# Status
# -------------------------------------------------------------
scheduler_status()
{
cat <<EOF

DSM Scheduler

Tasks:
$(jobs_list | wc -l)

Database:
$JOBS_DB

Estado:
ONLINE
EOF
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
case "$1" in
run)
scheduler_run
;;
check)
scheduler_check
;;
import)
scheduler_import_tasks
;;
status)
scheduler_status
;;
*)
cat <<EOF
DSM Scheduler

Uso:
scheduler.sh run
scheduler.sh check
scheduler.sh import
scheduler.sh status
EOF
;;
esac
