#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Installation Event Adapter
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/core/events.sh"
source "${DSM_ROOT}/installer/operation_state.sh"
source "${DSM_ROOT}/installer/atomic_progress.sh"

install_event_log()
{
    echo "[DSM][INSTALL-EVENT] $*"
}

install_event_error()
{
    echo "[DSM][INSTALL-EVENT][ERRO] $*" >&2
}

install_event_node_id()
{
    if [[ -n "${DSM_NODE_ID:-}" ]]
    then
        echo "${DSM_NODE_ID}"
        return 0
    fi

    hostname -s
}

install_event_engine_available()
{
    if ! declare -F dsm_event_json >/dev/null
    then
        install_event_error "Core Event Engine não implementa dsm_event_json()."
        return 1
    fi

    return 0
}

install_event_severity()
{
    local TYPE="${1:-}"

    case "${TYPE}" in
        INSTALL_FAILED|UPDATE_FAILED|ROLLBACK_FAILED|INSTALL_VALIDATION_FAILED)
            echo "ERROR"
        ;;
        *)
            echo "INFO"
        ;;
    esac
}

install_event_type_valid()
{
    local TYPE="${1:-}"

    case "${TYPE}" in
        INSTALL_STARTED|INSTALL_COMPLETED|INSTALL_FAILED|UPDATE_STARTED|UPDATE_COMPLETED|UPDATE_FAILED|ROLLBACK_STARTED|ROLLBACK_COMPLETED|ROLLBACK_FAILED|INSTALL_VALIDATION_FAILED)
            return 0
        ;;
    esac

    return 1
}

install_event_validate_data()
{
    local DATA="${1:-}"

    [[ -n "${DATA}" ]] || DATA='{}'

    if ! jq -e 'type == "object"' >/dev/null 2>&1 <<< "${DATA}"
    then
        install_event_error "Payload precisa ser objeto JSON válido."
        return 1
    fi

    return 0
}

install_event_emit()
{
    local TYPE="${1:-}"
    local GAME_ID="${2:-}"
    local PROVIDER="${3:-unknown}"
    local DATA="${4:-}"

    local SEVERITY
    local NODE_ID

    [[ -n "${DATA}" ]] || DATA='{}'

    install_event_engine_available || return 1

    if ! install_event_type_valid "${TYPE}"
    then
        install_event_error "Tipo de evento inválido: ${TYPE}"
        return 1
    fi

    if [[ -z "${GAME_ID}" ]]
    then
        install_event_error "GAME_ID não informado."
        return 1
    fi

    install_event_validate_data "${DATA}" || return 1

    SEVERITY="$(install_event_severity "${TYPE}")"
    NODE_ID="$(install_event_node_id)"

    DATA="$(
        jq -c \
            --arg provider "${PROVIDER}" \
            '. + {provider: $provider}' \
            <<< "${DATA}"
    )" || return 1

    if ! dsm_event_json \
        "${TYPE}" \
        "installation" \
        "${SEVERITY}" \
        "${DATA}" \
        "Capivara" \
        "${NODE_ID}" \
        "${GAME_ID}" \
        "${DSM_INSTANCE:-}"
    then
        install_event_error "Falha ao publicar evento universal: ${TYPE}"
        return 1
    fi

    if declare -F install_operation_from_event >/dev/null
    then
        if ! install_operation_from_event \
            "${TYPE}" \
            "${GAME_ID}" \
            "${PROVIDER}" \
            "${NODE_ID}" \
            "${DATA}" \
            "${DSM_INSTANCE:-}"
        then
            install_event_error "Evento publicado, mas falhou ao atualizar estado operacional: ${TYPE}"
        fi
    fi

    install_event_log "${TYPE}"
    return 0
}

install_event_operation_data()
{
    local PREVIOUS_VERSION="${1:-unknown}"
    local VERSION="${2:-unknown}"
    local ROLLBACK="${3:-false}"

    case "${ROLLBACK}" in
        true|false) ;;
        yes) ROLLBACK=true ;;
        no) ROLLBACK=false ;;
        *) ROLLBACK=false ;;
    esac

    jq -cn \
        --arg previous_version "${PREVIOUS_VERSION}" \
        --arg version "${VERSION}" \
        --argjson rollback_available "${ROLLBACK}" \
        '{previous_version: $previous_version, version: $version, rollback_available: $rollback_available}'
}

install_event_install_started()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local VERSION="${3:-unknown}"
    local DATA

    DATA="$(jq -cn --arg version "${VERSION}" '{version: $version}')"
    install_event_emit "INSTALL_STARTED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_install_completed()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local PREVIOUS_VERSION="${3:-unknown}"
    local VERSION="${4:-unknown}"
    local ROLLBACK="${5:-false}"
    local DATA

    DATA="$(install_event_operation_data "${PREVIOUS_VERSION}" "${VERSION}" "${ROLLBACK}")"
    install_event_emit "INSTALL_COMPLETED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_install_failed()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local REASON="${3:-unknown}"
    local DATA

    DATA="$(jq -cn --arg reason "${REASON}" '{reason: $reason}')"
    install_event_emit "INSTALL_FAILED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_update_started()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local VERSION="${3:-unknown}"
    local DATA

    DATA="$(jq -cn --arg version "${VERSION}" '{current_version: $version}')"
    install_event_emit "UPDATE_STARTED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_update_completed()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local PREVIOUS_VERSION="${3:-unknown}"
    local VERSION="${4:-unknown}"
    local ROLLBACK="${5:-false}"
    local DATA

    DATA="$(install_event_operation_data "${PREVIOUS_VERSION}" "${VERSION}" "${ROLLBACK}")"
    install_event_emit "UPDATE_COMPLETED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_update_failed()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local REASON="${3:-unknown}"
    local DATA

    DATA="$(jq -cn --arg reason "${REASON}" '{reason: $reason}')"
    install_event_emit "UPDATE_FAILED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_rollback_started()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local VERSION="${3:-unknown}"
    local DATA

    DATA="$(jq -cn --arg version "${VERSION}" '{current_version: $version}')"
    install_event_emit "ROLLBACK_STARTED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_rollback_completed()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local PREVIOUS_VERSION="${3:-unknown}"
    local VERSION="${4:-unknown}"
    local ROLLBACK="${5:-false}"
    local DATA

    DATA="$(install_event_operation_data "${PREVIOUS_VERSION}" "${VERSION}" "${ROLLBACK}")"
    install_event_emit "ROLLBACK_COMPLETED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_rollback_failed()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local REASON="${3:-unknown}"
    local DATA

    DATA="$(jq -cn --arg reason "${REASON}" '{reason: $reason}')"
    install_event_emit "ROLLBACK_FAILED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

install_event_validation_failed()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local VERSION="${3:-unknown}"
    local REASON="${4:-integrity_check_failed}"
    local DATA

    DATA="$(jq -cn --arg version "${VERSION}" --arg reason "${REASON}" '{version: $version, reason: $reason}')"
    install_event_emit "INSTALL_VALIDATION_FAILED" "${GAME_ID}" "${PROVIDER}" "${DATA}"
}

export -f install_event_log
export -f install_event_error
export -f install_event_node_id
export -f install_event_engine_available
export -f install_event_severity
export -f install_event_type_valid
export -f install_event_validate_data
export -f install_event_emit
export -f install_event_operation_data
export -f install_event_install_started
export -f install_event_install_completed
export -f install_event_install_failed
export -f install_event_update_started
export -f install_event_update_completed
export -f install_event_update_failed
export -f install_event_rollback_started
export -f install_event_rollback_completed
export -f install_event_rollback_failed
export -f install_event_validation_failed
