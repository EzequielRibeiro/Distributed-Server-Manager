#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Installation Operation Progress Adapter
#
# Atualiza stage/progress da operação corrente sem alterar o
# histórico de eventos. Pode ser chamado pelo Atomic Engine e
# pelos providers durante uma operação real.
#
# Regras:
# - somente uma operação running pode receber progresso;
# - progresso nunca regride dentro da mesma operação;
# - estados completed/failed são terminais e não são alterados.
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/installer/operation_state.sh"

install_operation_progress_update()
{
    local STAGE="${1:-processing}"
    local PROGRESS="${2:-0}"
    local MESSAGE="${3:-}"

    install_operation_init || return 1

    if [[ ! "${PROGRESS}" =~ ^[0-9]+$ ]]
    then
        PROGRESS=0
    fi

    (( PROGRESS < 0 )) && PROGRESS=0
    (( PROGRESS > 100 )) && PROGRESS=100

    # O lock fica confinado ao subshell. Ao terminar, o descritor
    # e o flock são sempre liberados, evitando deadlock.
    (
        exec 8>"${OPERATION_LOCK}"
        flock 8

        local CURRENT_STATUS CURRENT_PROGRESS NOW TMP

        CURRENT_STATUS="$(jq -r '.status // "idle"' "${OPERATION_FILE}" 2>/dev/null || echo idle)"
        CURRENT_PROGRESS="$(jq -r '.progress // 0' "${OPERATION_FILE}" 2>/dev/null || echo 0)"

        [[ "${CURRENT_PROGRESS}" =~ ^[0-9]+$ ]] || CURRENT_PROGRESS=0

        # Progress adapters nunca iniciam uma operação. O início
        # pertence aos eventos INSTALL/UPDATE/ROLLBACK_STARTED.
        case "${CURRENT_STATUS}" in
            running|starting|queued|pending)
                ;;
            *)
                exit 0
                ;;
        esac

        # Progresso deve ser monotônico. Se um módulo atrasado
        # tentar publicar valor menor, preservamos stage/progress
        # atuais para evitar saltos visuais para trás.
        if (( PROGRESS < CURRENT_PROGRESS ))
        then
            exit 0
        fi

        NOW="$(date +%s)"
        TMP="$(mktemp "${OPERATION_DIR}/progress.XXXXXX.json")" || exit 1

        if ! jq \
            --arg stage "${STAGE}" \
            --arg message "${MESSAGE}" \
            --argjson progress "${PROGRESS}" \
            --argjson updated_at "${NOW}" \
            '
            if type != "object" then . else
                .stage = $stage |
                .progress = $progress |
                .updated_at = $updated_at |
                .message = (if $message == "" then (.message // null) else $message end)
            end
            ' "${OPERATION_FILE}" > "${TMP}"
        then
            rm -f "${TMP}"
            exit 1
        fi

        if ! jq -e 'type == "object"' "${TMP}" >/dev/null
        then
            rm -f "${TMP}"
            exit 1
        fi

        mv -f "${TMP}" "${OPERATION_FILE}"
    )
}

install_operation_progress_safe()
{
    if declare -F install_operation_progress_update >/dev/null 2>&1
    then
        install_operation_progress_update "$@" || true
    fi
}

export -f install_operation_progress_update
export -f install_operation_progress_safe
