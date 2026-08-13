#!/bin/bash
# =============================================================
# DSM Scheduler Jobs Manager
#
# Arquivo:
#   scheduler/jobs.sh
#
# Responsável:
#   - Criar jobs
#   - Listar jobs
#   - Remover jobs
#   - Atualizar jobs
#   - Ativar/desativar jobs
#   - Importar tasks
#
# DSM Version:
#   1.2.2
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
SCHEDULER_DIR="${DSM_ROOT}/scheduler"
TASKS_DIR="${SCHEDULER_DIR}/tasks"
JOBS_DB="${SCHEDULER_DIR}/jobs.db"
LOCK_FILE="${DSM_ROOT}/cache/scheduler_jobs.lock"
LOG_MODULE="scheduler"

# =============================================================
# LOCK
# =============================================================

jobs_lock()
{
    mkdir -p "$(dirname "$LOCK_FILE")"

    if declare -f lock_acquire >/dev/null
    then
        lock_acquire "$LOCK_FILE"
        return $?
    fi

    if ! mkdir "${LOCK_FILE}.d" 2>/dev/null
    then
        echo "Erro: jobs.db bloqueado"
        return 1
    fi
}

jobs_unlock()
{
    if declare -f lock_release >/dev/null
    then
        lock_release "$LOCK_FILE"
    else
        rm -rf "${LOCK_FILE}.d"
    fi
}

# =============================================================
# DEPENDÊNCIAS
# =============================================================

jobs_check_dependencies()
{
    command -v jq >/dev/null 2>&1
}

# =============================================================
# INICIALIZAÇÃO
# =============================================================

jobs_init()
{
    jobs_check_dependencies || {
        echo "Erro: jq não instalado"
        return 1
    }

    mkdir -p "$SCHEDULER_DIR"

    if [ ! -f "$JOBS_DB" ]
    then
        echo '{"jobs":[]}' > "$JOBS_DB"
    fi
}

# =============================================================
# VALIDAÇÕES
# =============================================================

jobs_validate_schedule()
{
    local S="$1"

    [[ "$S" =~ ^[0-9]{2}:[0-9]{2}$ ]] && return 0
    [[ "$S" =~ ^@every:[0-9]+$ ]] && return 0

    return 1
}

jobs_exists()
{
    local NAME="$1"

    jq -e \
    --arg name "$NAME" \
    '.jobs[] | select(.name==$name)' \
    "$JOBS_DB" >/dev/null
}

# =============================================================
# LISTAR
# =============================================================

jobs_list()
{
    jobs_init || return 1

    jq -r '
    .jobs[]
    |
    [
        .name,
        .schedule,
        .command,
        .enabled,
        .file
    ]
    |
    @tsv
    ' "$JOBS_DB" | tr "\t" "|"
}

# =============================================================
# SHOW
# =============================================================

jobs_show()
{
    local NAME="$1"

    jobs_init || return 1

    jq \
    --arg name "$NAME" '
    .jobs[]
    |
    select(.name==$name)
    ' "$JOBS_DB"
}

# =============================================================
# IMPORTAR TASKS
# =============================================================

jobs_import_tasks()
{
    jobs_init || return 1

    [ -d "$TASKS_DIR" ] || return 0

    for TASK in "$TASKS_DIR"/*.task
    do
        [ -f "$TASK" ] || continue

        unset NAME
        unset SCHEDULE
        unset COMMAND
        unset ENABLED

        source "$TASK"

        [ -z "$NAME" ] && continue

        if ! jobs_exists "$NAME"
        then
            jobs_add \
            "$NAME" \
            "$SCHEDULE" \
            "$COMMAND" \
            "$ENABLED" \
            "$TASK"
        fi
    done
}

# =============================================================
# ADD
# =============================================================

jobs_add()
{
    local NAME="$1"
    local SCHEDULE="$2"
    local COMMAND="$3"
    local ENABLED="$4"
    local FILE="$5"

    jobs_init || return 1

    jobs_lock || return 1

    if [ -z "$NAME" ] ||
       [ -z "$SCHEDULE" ] ||
       [ -z "$COMMAND" ]
    then
        echo "Erro: parâmetros obrigatórios ausentes"
        jobs_unlock
        return 1
    fi

    if ! jobs_validate_schedule "$SCHEDULE"
    then
        echo "Erro: schedule inválido"
        jobs_unlock
        return 1
    fi

    if [[ "$ENABLED" != "0" &&
          "$ENABLED" != "1" ]]
    then
        echo "Erro: enabled deve ser 0 ou 1"
        jobs_unlock
        return 1
    fi

    if jobs_exists "$NAME"
    then
        echo "Erro: job já existe"
        jobs_unlock
        return 1
    fi

    local TMP
    TMP=$(mktemp)

    jq \
    --arg name "$NAME" \
    --arg schedule "$SCHEDULE" \
    --arg command "$COMMAND" \
    --arg file "$FILE" \
    --argjson enabled "$ENABLED" '
    .jobs += [
    {
    name:$name,
    schedule:$schedule,
    command:$command,
    enabled:$enabled,
    file:$file,
    created_at:(now|todate),
    updated_at:(now|todate)
    }
    ]
    ' "$JOBS_DB" > "$TMP"

    mv "$TMP" "$JOBS_DB"

    jobs_unlock
}

# =============================================================
# UPDATE
# =============================================================

jobs_update()
{
    local NAME="$1"
    local FIELD="$2"
    local VALUE="$3"

    jobs_init || return 1

    jobs_lock || return 1

    if ! jobs_exists "$NAME"
    then
        echo "Erro: job inexistente"
        jobs_unlock
        return 1
    fi

    case "$FIELD" in
    schedule)
        jobs_validate_schedule "$VALUE" ||
        {
            echo "Schedule inválido"
            jobs_unlock
            return 1
        }
    ;;
    enabled)
        [[ "$VALUE" =~ ^[01]$ ]] ||
        {
            echo "enabled inválido"
            jobs_unlock
            return 1
        }
    ;;
    command|file)
    ;;
    *)
        echo "Campo inválido"
        jobs_unlock
        return 1
    ;;
    esac

    local TMP
    TMP=$(mktemp)

    jq \
    --arg name "$NAME" \
    --arg field "$FIELD" \
    --arg value "$VALUE" '
    .jobs |= map(
    if .name==$name
    then
        .[$field]=$value |
        .updated_at=(now|todate)
    else
        .
    end
    )
    ' "$JOBS_DB" > "$TMP"

    mv "$TMP" "$JOBS_DB"

    jobs_unlock
}

# =============================================================
# REMOVE
# =============================================================

jobs_remove()
{
    local NAME="$1"

    jobs_init || return 1

    jobs_lock || return 1

    if ! jobs_exists "$NAME"
    then
        echo "Erro: job não encontrado"
        jobs_unlock
        return 1
    fi

    local TMP
    TMP=$(mktemp)

    jq \
    --arg name "$NAME" '
    .jobs |= map(select(.name!=$name))
    ' "$JOBS_DB" > "$TMP"

    mv "$TMP" "$JOBS_DB"

    jobs_unlock
}

# =============================================================
# ENABLE / DISABLE
# =============================================================

jobs_enable()
{
    jobs_set_enabled "$1" 1
}

jobs_disable()
{
    jobs_set_enabled "$1" 0
}

jobs_set_enabled()
{
    local NAME="$1"
    local STATE="$2"

    jobs_update "$NAME" enabled "$STATE"
}

# =============================================================
# CLEAR
# =============================================================

jobs_clear()
{
    jobs_lock || return 1
    echo '{"jobs":[]}' > "$JOBS_DB"
    jobs_unlock
}

# =============================================================
# CLI
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
case "$1" in
list)
jobs_list
;;
show)
jobs_show "$2"
;;
import)
jobs_import_tasks
;;
add)
jobs_add "$2" "$3" "$4" "$5" "$6"
;;
update)
jobs_update "$2" "$3" "$4"
;;
remove)
jobs_remove "$2"
;;
enable)
jobs_enable "$2"
;;
disable)
jobs_disable "$2"
;;
clear)
jobs_clear
;;
*)
cat <<EOF
DSM Jobs Manager v1.2.2

Uso:
jobs.sh list
jobs.sh show JOB
jobs.sh import
jobs.sh add NAME SCHEDULE COMMAND ENABLED FILE
jobs.sh update JOB FIELD VALUE
jobs.sh remove JOB
jobs.sh enable JOB
jobs.sh disable JOB
jobs.sh clear
EOF
;;
esac
fi
