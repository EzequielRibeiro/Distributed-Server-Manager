#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Installation Operation State Engine
#
# Mantém o estado operacional atual usado pelo Dashboard em:
#   runtime/operations/current.json
#
# O histórico continua pertencendo à Universal Event Platform.
# Este arquivo representa somente a operação corrente/mais recente.
#
# IMPORTANTE:
# Este módulo é carregado via `source`. Por isso ele NÃO altera
# opções globais do shell chamador com `set -e`, `set -u` etc.
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

OPERATION_DIR="${DSM_ROOT}/runtime/operations"
OPERATION_FILE="${OPERATION_DIR}/current.json"
OPERATION_LOCK="${OPERATION_DIR}/current.lock"

install_operation_init()
{
    mkdir -p "${OPERATION_DIR}"

    if [[ ! -f "${OPERATION_FILE}" ]]
    then
        printf '%s\n' '{"status":"idle","operation":null}' > "${OPERATION_FILE}"
    fi

    if ! jq -e 'type == "object"' "${OPERATION_FILE}" >/dev/null 2>&1
    then
        cp -f "${OPERATION_FILE}" "${OPERATION_FILE}.invalid" 2>/dev/null || true
        printf '%s\n' '{"status":"idle","operation":null}' > "${OPERATION_FILE}"
    fi
}

install_operation_generate_id()
{
    if command -v uuidgen >/dev/null 2>&1
    then
        printf 'op-%s\n' "$(uuidgen | tr '[:upper:]' '[:lower:]')"
        return
    fi

    printf 'op-%s-%s\n' "$(date +%s)" "$RANDOM"
}

install_operation_type_from_event()
{
    case "${1:-}" in
        INSTALL_*) echo "install" ;;
        UPDATE_*) echo "update" ;;
        ROLLBACK_*) echo "rollback" ;;
        *) echo "unknown" ;;
    esac
}

install_operation_status_from_event()
{
    case "${1:-}" in
        *_STARTED) echo "running" ;;
        *_COMPLETED) echo "completed" ;;
        *_FAILED|INSTALL_VALIDATION_FAILED) echo "failed" ;;
        *) echo "running" ;;
    esac
}

install_operation_stage_from_event()
{
    case "${1:-}" in
        INSTALL_STARTED|UPDATE_STARTED) echo "downloading" ;;
        ROLLBACK_STARTED) echo "restoring" ;;
        INSTALL_VALIDATION_FAILED) echo "validating" ;;
        *_COMPLETED) echo "completed" ;;
        *_FAILED) echo "failed" ;;
        *) echo "processing" ;;
    esac
}

install_operation_progress_from_event()
{
    local EVENT_TYPE="${1:-}"
    local CURRENT_PROGRESS="${2:-0}"

    case "${EVENT_TYPE}" in
        INSTALL_STARTED|UPDATE_STARTED) echo 5 ;;
        ROLLBACK_STARTED) echo 10 ;;
        INSTALL_VALIDATION_FAILED) echo 70 ;;
        *_COMPLETED) echo 100 ;;
        *_FAILED)
            if [[ "${CURRENT_PROGRESS}" =~ ^[0-9]+$ ]]
            then
                echo "${CURRENT_PROGRESS}"
            else
                echo 0
            fi
        ;;
        *) echo "${CURRENT_PROGRESS:-0}" ;;
    esac
}

install_operation_from_event()
{
    local EVENT_TYPE="${1:-}"
    local GAME_ID="${2:-}"
    local PROVIDER="${3:-unknown}"
    local NODE_ID="${4:-unknown}"
    local DATA="${5:-{}}"
    local INSTANCE="${6:-${DSM_INSTANCE:-}}"

    install_operation_init || return 1

    # O lock vive somente dentro deste subshell. Ao sair dele,
    # o descritor e o flock são sempre liberados, inclusive em erro.
    (
        exec 9>"${OPERATION_LOCK}"
        flock 9

        local NOW OP_TYPE STATUS STAGE CURRENT_ID CURRENT_PROGRESS OPERATION_ID
        local VERSION PREVIOUS_VERSION REASON PROGRESS STARTED_AT TMP

        NOW="$(date +%s)"
        OP_TYPE="$(install_operation_type_from_event "${EVENT_TYPE}")"
        STATUS="$(install_operation_status_from_event "${EVENT_TYPE}")"
        STAGE="$(install_operation_stage_from_event "${EVENT_TYPE}")"

        CURRENT_ID="$(jq -r '.operation_id // .operation.operation_id // empty' "${OPERATION_FILE}" 2>/dev/null || true)"
        CURRENT_PROGRESS="$(jq -r '.progress // .operation.progress // 0' "${OPERATION_FILE}" 2>/dev/null || echo 0)"

        if [[ "${EVENT_TYPE}" == *_STARTED || -z "${CURRENT_ID}" ]]
        then
            OPERATION_ID="$(install_operation_generate_id)"
            STARTED_AT="${NOW}"
        else
            OPERATION_ID="${CURRENT_ID}"
            STARTED_AT="$(jq -r '.started_at // .operation.started_at // empty' "${OPERATION_FILE}" 2>/dev/null || true)"
            [[ -n "${STARTED_AT}" && "${STARTED_AT}" != "null" ]] || STARTED_AT="${NOW}"
        fi

        VERSION="$(jq -r '.version // .current_version // empty' <<< "${DATA}" 2>/dev/null || true)"
        PREVIOUS_VERSION="$(jq -r '.previous_version // empty' <<< "${DATA}" 2>/dev/null || true)"
        REASON="$(jq -r '.reason // empty' <<< "${DATA}" 2>/dev/null || true)"
        PROGRESS="$(install_operation_progress_from_event "${EVENT_TYPE}" "${CURRENT_PROGRESS}")"

        TMP="$(mktemp "${OPERATION_DIR}/current.XXXXXX.json")" || exit 1

        if ! jq -cn \
            --arg operation_id "${OPERATION_ID}" \
            --arg type "${OP_TYPE}" \
            --arg status "${STATUS}" \
            --arg stage "${STAGE}" \
            --arg server "${NODE_ID}" \
            --arg game "${GAME_ID}" \
            --arg instance "${INSTANCE}" \
            --arg provider "${PROVIDER}" \
            --arg version "${VERSION}" \
            --arg previous_version "${PREVIOUS_VERSION}" \
            --arg reason "${REASON}" \
            --argjson progress "${PROGRESS}" \
            --argjson started_at "${STARTED_AT}" \
            --argjson updated_at "${NOW}" \
            '{
                operation_id: $operation_id,
                type: $type,
                status: $status,
                stage: $stage,
                progress: $progress,
                server: (if $server == "" then null else $server end),
                game: (if $game == "" then null else $game end),
                instance: (if $instance == "" then null else $instance end),
                provider: (if $provider == "" then null else $provider end),
                version: (if $version == "" then null else $version end),
                previous_version: (if $previous_version == "" then null else $previous_version end),
                reason: (if $reason == "" then null else $reason end),
                started_at: $started_at,
                updated_at: $updated_at
            }' > "${TMP}"
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

export -f install_operation_init
export -f install_operation_generate_id
export -f install_operation_type_from_event
export -f install_operation_status_from_event
export -f install_operation_stage_from_event
export -f install_operation_progress_from_event
export -f install_operation_from_event
