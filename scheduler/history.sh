#!/bin/bash
# =============================================================
# scheduler/history.sh - MÓDULO 07 (SCHEDULER)
#
# Histórico de execuções das tarefas agendadas
#
# DSM Version:
#   1.2.2
#
# Correções:
#   - Lock de escrita
#   - Rotação automática
#   - Controle de tamanho
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

LOG_MODULE="scheduler"

HISTORY_FILE="${DSM_ROOT}/logs/scheduler_history.log"
LOCK_FILE="${DSM_ROOT}/cache/scheduler_history.lock"

# -------------------------------------------------------------
# Configuração rotação
# -------------------------------------------------------------
MAX_SIZE="${SCHEDULER_HISTORY_MAX_SIZE:-5242880}"
# 5MB
MAX_ROTATE="${SCHEDULER_HISTORY_ROTATE_COUNT:-5}"

# -------------------------------------------------------------
# Lock
# -------------------------------------------------------------
history_lock()
{
    mkdir -p "$(dirname "$LOCK_FILE")"

    if [ -e "${LOCK_FILE}.d" ]
    then
        return 1
    fi

    mkdir "${LOCK_FILE}.d" 2>/dev/null
}

history_unlock()
{
    rm -rf "${LOCK_FILE}.d"
}

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
history_init()
{
    mkdir -p "$(dirname "$HISTORY_FILE")"

    if [ ! -f "$HISTORY_FILE" ]
    then
        touch "$HISTORY_FILE"
    fi
}

# -------------------------------------------------------------
# Rotação
# -------------------------------------------------------------
history_rotate()
{
    history_init

    local SIZE
    SIZE=$(stat -c%s "$HISTORY_FILE" 2>/dev/null)

    if [ "$SIZE" -lt "$MAX_SIZE" ]
    then
        return 0
    fi

    local COUNT="$MAX_ROTATE"

    while [ "$COUNT" -gt 0 ]
    do
        local OLD=$((COUNT-1))

        if [ "$OLD" -eq 0 ]
        then
            if [ -f "$HISTORY_FILE" ]
            then
                mv \
                "$HISTORY_FILE" \
                "${HISTORY_FILE}.${COUNT}"
            fi
        else
            if [ -f "${HISTORY_FILE}.${OLD}" ]
            then
                mv \
                "${HISTORY_FILE}.${OLD}" \
                "${HISTORY_FILE}.${COUNT}"
            fi
        fi

        COUNT=$((COUNT-1))
    done

    touch "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Registrar execução
#
# Uso:
#
# history_record nome rc duração
#
# -------------------------------------------------------------
history_record()
{
    local NAME="$1"
    local RC="$2"
    local DURATION="$3"

    history_init

    history_lock

    if [ $? -ne 0 ]
    then
        echo "Histórico bloqueado"
        return 1
    fi

    trap history_unlock EXIT

    if [ -z "$NAME" ]
    then
        history_unlock
        trap - EXIT
        return 1
    fi

    RC="${RC:-1}"
    DURATION="${DURATION:-0}"

    history_rotate

    local TS
    TS=$(date '+%Y-%m-%d %H:%M:%S')

    local STATUS="OK"

    if [ "$RC" -ne 0 ]
    then
        STATUS="FALHA"
    fi

    echo \
"[$TS] $NAME - $STATUS (rc=$RC, ${DURATION}s)" \
>> "$HISTORY_FILE"

    history_unlock
    trap - EXIT
}

# -------------------------------------------------------------
# Últimas execuções
# -------------------------------------------------------------
history_recent()
{
    local N="${1:-20}"

    history_init

    tail -n "$N" "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Total de execuções
# -------------------------------------------------------------
history_count()
{
    history_init

    wc -l < "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Limpar histórico
# -------------------------------------------------------------
history_clear()
{
    history_init

    history_lock || return 1

    > "$HISTORY_FILE"

    history_unlock
}

# -------------------------------------------------------------
# Buscar tarefa
# -------------------------------------------------------------
history_find()
{
    local NAME="$1"

    history_init

    grep -F "$NAME" "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Exportar histórico
# -------------------------------------------------------------
history_export()
{
    local FILE="$1"
    local N="${2:-50}"

    history_init

    if [ -z "$FILE" ]
    then
        return 1
    fi

    tail -n "$N" "$HISTORY_FILE" > "$FILE"
}

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
case "$1" in
recent)
history_recent "$2"
;;
count)
history_count
;;
find)
history_find "$2"
;;
clear)
history_clear
;;
export)
history_export "$2" "$3"
;;
rotate)
history_rotate
;;
*)
cat <<EOF
DSM Scheduler History

Uso:
history.sh recent [quantidade]
history.sh count
history.sh find JOB
history.sh clear
history.sh export arquivo [quantidade]
history.sh rotate
EOF
;;
esac
fi
