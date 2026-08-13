#!/bin/bash
# =============================================================
# DSM Scheduler API
#
# Arquivo:
#   scheduler/scheduler_api.sh
#
# Responsável:
#   Interface API do Scheduler DSM
#
# DSM Version:
#   1.2.2
#
# Recursos:
#   - Dashboard
#   - JSON API
#   - Execução manual
#   - Controle de jobs
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
SCHEDULER_DIR="${DSM_ROOT}/scheduler"

JOBS_MODULE="${SCHEDULER_DIR}/jobs.sh"
EXECUTOR_MODULE="${SCHEDULER_DIR}/executor.sh"
HISTORY_MODULE="${SCHEDULER_DIR}/history.sh"
CRON_MODULE="${SCHEDULER_DIR}/cron_engine.sh"

# -------------------------------------------------------------
# Carregar módulos
# -------------------------------------------------------------
source "$JOBS_MODULE"
source "$EXECUTOR_MODULE"
source "$HISTORY_MODULE"
source "$CRON_MODULE"

# -------------------------------------------------------------
# JSON helper
# -------------------------------------------------------------
json_error()
{
cat <<EOF
{
 "status":"error",
 "message":"$1"
}
EOF
}

json_ok()
{
cat <<EOF
{
 "status":"ok",
 "message":"$1"
}
EOF
}

# -------------------------------------------------------------
# Listar jobs JSON
# -------------------------------------------------------------
api_list()
{
    jobs_init || return 1

    jq -c '
    {
        name:.name,
        schedule:.schedule,
        command:.command,
        enabled:.enabled,
        file:.file,
        created_at:.created_at,
        updated_at:.updated_at
    }
    ' "$JOBS_DB"
}

# -------------------------------------------------------------
# Mostrar job
# -------------------------------------------------------------
api_show()
{
    local NAME="$1"

    if [ -z "$NAME" ]
    then
        json_error "job não informado"
        return 1
    fi

    if ! jobs_show "$NAME"
    then
        json_error "job não encontrado"
        return 1
    fi
}

# -------------------------------------------------------------
# Adicionar
# -------------------------------------------------------------
api_add()
{
    jobs_add \
    "$1" \
    "$2" \
    "$3" \
    "$4" \
    "$5"
}

# -------------------------------------------------------------
# Atualizar
# -------------------------------------------------------------
api_update()
{
    jobs_update \
    "$1" \
    "$2" \
    "$3"
}

# -------------------------------------------------------------
# Remover
# -------------------------------------------------------------
api_remove()
{
    jobs_remove "$1"
}

# -------------------------------------------------------------
# Ativar
# -------------------------------------------------------------
api_enable()
{
    jobs_enable "$1"
}

# -------------------------------------------------------------
# Desativar
# -------------------------------------------------------------
api_disable()
{
    jobs_disable "$1"
}

# -------------------------------------------------------------
# Próxima execução
# -------------------------------------------------------------
api_next()
{
    local SCHEDULE="$1"
    local TS

    TS=$(cron_next_run "$SCHEDULE")

    if [ -n "$TS" ]
    then
        date \
        -d "@$TS" \
        '+%Y-%m-%d %H:%M:%S'
    else
        echo "Sem próxima execução"
    fi
}

# -------------------------------------------------------------
# Executar job manualmente
# -------------------------------------------------------------
api_run()
{
    local JOB="$1"

    if [ -z "$JOB" ]
    then
        json_error \
        "job não informado"
        return 1
    fi

    local DATA

    DATA=$(jobs_show "$JOB")

    if [ -z "$DATA" ]
    then
        json_error \
        "job não encontrado"
        return 1
    fi

    local COMMAND

    COMMAND=$(echo "$DATA" | jq -r '.command')

    executor_run \
    "$JOB" \
    "$COMMAND"

    if [ $? -eq 0 ]
    then
        json_ok \
        "job executado: $JOB"
    else
        json_error \
        "falha executando job: $JOB"
        return 1
    fi
}

# -------------------------------------------------------------
# Histórico recente
# -------------------------------------------------------------
api_history()
{
    history_recent "${1:-20}"
}

# -------------------------------------------------------------
# Status Scheduler
# -------------------------------------------------------------
api_status()
{
local COUNT
COUNT=$(jobs_list | wc -l)

cat <<EOF
{
 "scheduler":"online",
 "jobs":$COUNT,
 "database":"$JOBS_DB",
 "history":"$HISTORY_FILE"
}
EOF
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
case "$1" in
list)
api_list
;;
show)
api_show "$2"
;;
add)
api_add \
"$2" \
"$3" \
"$4" \
"$5" \
"$6"
;;
update)
api_update \
"$2" \
"$3" \
"$4"
;;
remove)
api_remove "$2"
;;
enable)
api_enable "$2"
;;
disable)
api_disable "$2"
;;
next)
api_next "$2"
;;
run)
api_run "$2"
;;
history)
api_history "$2"
;;
status)
api_status
;;
*)
cat <<EOF
DSM Scheduler API v1.2.2

Uso:
scheduler_api.sh list
scheduler_api.sh show JOB
scheduler_api.sh add NAME SCHEDULE COMMAND ENABLED FILE
scheduler_api.sh update JOB FIELD VALUE
scheduler_api.sh remove JOB
scheduler_api.sh enable JOB
scheduler_api.sh disable JOB
scheduler_api.sh next SCHEDULE
scheduler_api.sh run JOB
scheduler_api.sh history [N]
scheduler_api.sh status
EOF
;;
esac
