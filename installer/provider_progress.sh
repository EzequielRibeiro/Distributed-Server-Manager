#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Universal Provider Progress Contract
#
# Contrato leve para providers publicarem progresso sem conhecer
# detalhes do Dashboard ou do arquivo current.json.
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# operation_progress.sh pode já estar carregado pelo manager.
if ! declare -F install_operation_progress_safe >/dev/null 2>&1
then
    source "${DSM_ROOT}/installer/operation_progress.sh"
fi

provider_progress_publish()
{
    local STAGE="${1:-downloading}"
    local PROGRESS="${2:-25}"
    local MESSAGE="${3:-}"

    if declare -F install_operation_progress_safe >/dev/null 2>&1
    then
        install_operation_progress_safe \
            "${STAGE}" \
            "${PROGRESS}" \
            "${MESSAGE}"
    fi
}

# Converte percentual 0..100 para uma faixa global, por padrão 25..75.
provider_progress_map_percent()
{
    local PERCENT="${1:-0}"
    local START="${2:-25}"
    local END="${3:-75}"

    PERCENT="${PERCENT%%.*}"
    [[ "${PERCENT}" =~ ^[0-9]+$ ]] || PERCENT=0
    [[ "${START}" =~ ^[0-9]+$ ]] || START=25
    [[ "${END}" =~ ^[0-9]+$ ]] || END=75

    (( PERCENT < 0 )) && PERCENT=0
    (( PERCENT > 100 )) && PERCENT=100
    (( END < START )) && END="${START}"

    echo $(( START + (PERCENT * (END - START) / 100) ))
}

# Monitora o crescimento de um arquivo enquanto PID estiver ativo.
# Uso: provider_progress_monitor_file PID FILE TOTAL_BYTES LABEL [START] [END]
provider_progress_monitor_file()
{
    local PID="${1:-}"
    local FILE="${2:-}"
    local TOTAL="${3:-0}"
    local LABEL="${4:-Provider}"
    local START="${5:-25}"
    local END="${6:-75}"

    [[ "${PID}" =~ ^[0-9]+$ ]] || return 0
    [[ "${TOTAL}" =~ ^[0-9]+$ ]] || TOTAL=0
    (( TOTAL > 0 )) || return 0

    local SIZE=0 PERCENT=0 GLOBAL=0 LAST=-1

    while kill -0 "${PID}" 2>/dev/null
    do
        if [[ -f "${FILE}" ]]
        then
            SIZE="$(stat -c %s "${FILE}" 2>/dev/null || echo 0)"
            [[ "${SIZE}" =~ ^[0-9]+$ ]] || SIZE=0

            PERCENT=$(( SIZE * 100 / TOTAL ))
            (( PERCENT > 100 )) && PERCENT=100

            if (( PERCENT != LAST ))
            then
                GLOBAL="$(provider_progress_map_percent "${PERCENT}" "${START}" "${END}")"
                provider_progress_publish \
                    "downloading" \
                    "${GLOBAL}" \
                    "${LABEL}: ${PERCENT}%"
                LAST="${PERCENT}"
            fi
        fi

        sleep 1
    done

    if [[ -f "${FILE}" ]]
    then
        SIZE="$(stat -c %s "${FILE}" 2>/dev/null || echo 0)"
        if [[ "${SIZE}" =~ ^[0-9]+$ && "${SIZE}" -ge "${TOTAL}" ]]
        then
            provider_progress_publish "downloading" "${END}" "${LABEL}: 100%"
        fi
    fi
}

export -f provider_progress_publish
export -f provider_progress_map_percent
export -f provider_progress_monitor_file
