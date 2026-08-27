#!/usr/bin/env bash
set -Eeuo pipefail

# Capivara installation events publish directly through the current
# database-backed Universal Event Platform. No JSON event queue is maintained.
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
source "${DSM_ROOT}/installer/operation_state.sh"
source "${DSM_ROOT}/installer/atomic_progress.sh"

install_event_log(){ echo "[DSM][INSTALL-EVENT] $*"; }
install_event_error(){ echo "[DSM][INSTALL-EVENT][ERRO] $*" >&2; }
install_event_node_id(){ [[ -n "${DSM_NODE_ID:-}" ]] && printf '%s\n' "${DSM_NODE_ID}" || hostname -s; }
install_event_engine_available(){
    [[ -f "${DSM_ROOT}/database/universal_events_cli.py" ]] || {
        install_event_error "Universal Event Platform indisponível."
        return 1
    }
}
install_event_severity(){
    case "${1:-}" in
        INSTALL_FAILED|UPDATE_FAILED|ROLLBACK_FAILED|INSTALL_VALIDATION_FAILED) echo "error" ;;
        *) echo "info" ;;
    esac
}
install_event_type_valid(){
    case "${1:-}" in
        INSTALL_STARTED|INSTALL_COMPLETED|INSTALL_FAILED|UPDATE_STARTED|UPDATE_COMPLETED|UPDATE_FAILED|ROLLBACK_STARTED|ROLLBACK_COMPLETED|ROLLBACK_FAILED|INSTALL_VALIDATION_FAILED) return 0 ;;
        *) return 1 ;;
    esac
}
install_event_validate_data(){
    local data="${1:-{}}"
    jq -e 'type == "object"' >/dev/null 2>&1 <<<"${data}" || {
        install_event_error "Payload precisa ser objeto JSON válido."
        return 1
    }
}

install_event_emit(){
    local type="${1:-}" game_id="${2:-}" provider="${3:-unknown}" data="${4:-{}}"
    local severity node_id enriched
    install_event_engine_available || return 1
    install_event_type_valid "${type}" || { install_event_error "Tipo de evento inválido: ${type}"; return 1; }
    [[ -n "${game_id}" ]] || { install_event_error "GAME_ID não informado."; return 1; }
    install_event_validate_data "${data}" || return 1
    severity="$(install_event_severity "${type}")"
    node_id="$(install_event_node_id)"
    enriched="$(jq -c --arg provider "${provider}" --arg game_id "${game_id}" '. + {provider:$provider,game_id:$game_id}' <<<"${data}")" || return 1

    # Installation/catalog operations can run before a Controller database has
    # been configured (for example package preparation and isolated tests).
    # In that case the event is an operational log only; once database config
    # exists, publication is durable and goes exclusively through the DB.
    if [[ -n "${DSM_DATABASE_DRIVER:-}" || -f "${DSM_ROOT}/config/dsm.conf" ]]
    then
        if ! PYTHONPATH="${DSM_ROOT}/database:${DSM_ROOT}" \
            python3 "${DSM_ROOT}/database/universal_events_cli.py" publish "${type}" \
                --source installation \
                --source-id "${node_id}" \
                --severity "${severity}" \
                ${DSM_INSTANCE:+--instance "${DSM_INSTANCE}"} \
                --actor-type system \
                --actor-id Capivara \
                --data-json "${enriched}" \
                --json >/dev/null
        then
            install_event_error "Falha ao publicar evento universal: ${type}"
            return 1
        fi
    fi

    if declare -F install_operation_from_event >/dev/null
    then
        install_operation_from_event "${type}" "${game_id}" "${provider}" "${node_id}" "${enriched}" "${DSM_INSTANCE:-}" \
            || install_event_error "Evento processado, mas falhou ao atualizar estado operacional: ${type}"
    fi
    install_event_log "${type}"
}

install_event_operation_data(){
    local previous_version="${1:-unknown}" version="${2:-unknown}" rollback="${3:-false}"
    case "${rollback}" in true|false) ;; yes) rollback=true ;; no|*) rollback=false ;; esac
    jq -cn --arg previous_version "${previous_version}" --arg version "${version}" --argjson rollback_available "${rollback}" \
        '{previous_version:$previous_version,version:$version,rollback_available:$rollback_available}'
}
install_event_install_started(){ local d; d="$(jq -cn --arg version "${3:-unknown}" '{version:$version}')"; install_event_emit INSTALL_STARTED "$1" "$2" "${d}"; }
install_event_install_completed(){ local d; d="$(install_event_operation_data "${3:-unknown}" "${4:-unknown}" "${5:-false}")"; install_event_emit INSTALL_COMPLETED "$1" "$2" "${d}"; }
install_event_install_failed(){ local d; d="$(jq -cn --arg reason "${3:-unknown}" '{reason:$reason}')"; install_event_emit INSTALL_FAILED "$1" "$2" "${d}"; }
install_event_update_started(){ local d; d="$(jq -cn --arg version "${3:-unknown}" '{current_version:$version}')"; install_event_emit UPDATE_STARTED "$1" "$2" "${d}"; }
install_event_update_completed(){ local d; d="$(install_event_operation_data "${3:-unknown}" "${4:-unknown}" "${5:-false}")"; install_event_emit UPDATE_COMPLETED "$1" "$2" "${d}"; }
install_event_update_failed(){ local d; d="$(jq -cn --arg reason "${3:-unknown}" '{reason:$reason}')"; install_event_emit UPDATE_FAILED "$1" "$2" "${d}"; }
install_event_rollback_started(){ local d; d="$(jq -cn --arg version "${3:-unknown}" '{current_version:$version}')"; install_event_emit ROLLBACK_STARTED "$1" "$2" "${d}"; }
install_event_rollback_completed(){ local d; d="$(install_event_operation_data "${3:-unknown}" "${4:-unknown}" "${5:-false}")"; install_event_emit ROLLBACK_COMPLETED "$1" "$2" "${d}"; }
install_event_rollback_failed(){ local d; d="$(jq -cn --arg reason "${3:-unknown}" '{reason:$reason}')"; install_event_emit ROLLBACK_FAILED "$1" "$2" "${d}"; }
install_event_validation_failed(){ local d; d="$(jq -cn --arg version "${3:-unknown}" --arg reason "${4:-integrity_check_failed}" '{version:$version,reason:$reason}')"; install_event_emit INSTALL_VALIDATION_FAILED "$1" "$2" "${d}"; }

export -f install_event_log install_event_error install_event_node_id install_event_engine_available
export -f install_event_severity install_event_type_valid install_event_validate_data install_event_emit
export -f install_event_operation_data install_event_install_started install_event_install_completed install_event_install_failed
export -f install_event_update_started install_event_update_completed install_event_update_failed
export -f install_event_rollback_started install_event_rollback_completed install_event_rollback_failed install_event_validation_failed
