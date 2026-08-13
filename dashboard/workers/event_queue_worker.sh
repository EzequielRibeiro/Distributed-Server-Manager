#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Universal Event Queue Worker
#
# Responsável por consumir eventos publicados em:
#   runtime/events/queue.json
#
# e consolidá-los em:
#   runtime/events/history.json
#
# Características:
# - preserva o worker legado baseado em logs
# - valida queue/history como arrays JSON
# - ignora eventos inválidos
# - evita duplicação no histórico pelo campo id
# - remove da fila somente os IDs processados no snapshot atual
# - preserva eventos adicionados à fila durante o processamento
# - suporta execução única (once) e daemon (run)
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_EVENT_QUEUE_INTERVAL="${DSM_EVENT_QUEUE_INTERVAL:-2}"
DSM_EVENT_HISTORY_LIMIT="${DSM_EVENT_HISTORY_LIMIT:-10000}"

EVENT_DIR="${DSM_ROOT}/runtime/events"
QUEUE_FILE="${EVENT_DIR}/queue.json"
HISTORY_FILE="${EVENT_DIR}/history.json"
LOCK_FILE="${EVENT_DIR}/event_queue_worker.lock"
LOG_FILE="${DSM_ROOT}/logs/event_queue_worker.log"

log()
{
    mkdir -p "$(dirname "${LOG_FILE}")"
    printf '%s [EVENT-QUEUE] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "${LOG_FILE}"
}

ensure_json_array()
{
    local FILE="$1"

    mkdir -p "$(dirname "${FILE}")"

    if [[ ! -f "${FILE}" ]]
    then
        printf '[]\n' > "${FILE}"
        return 0
    fi

    if ! jq -e 'type == "array"' "${FILE}" >/dev/null 2>&1
    then
        log "JSON inválido ou não-array em ${FILE}; preservando cópia .invalid"
        cp -f "${FILE}" "${FILE}.invalid" 2>/dev/null || true
        printf '[]\n' > "${FILE}"
    fi
}

validate_event()
{
    jq -e '
        type == "object"
        and (.id | type == "string" and length > 0)
        and (.type | type == "string" and length > 0)
        and (.category | type == "string" and length > 0)
        and (.timestamp | type == "number")
    ' >/dev/null 2>&1
}

process_once()
{
    ensure_json_array "${QUEUE_FILE}"
    ensure_json_array "${HISTORY_FILE}"

    # Lock apenas entre instâncias deste consumidor.
    # Produtores atuais não usam este lock; por isso a remoção final
    # é feita por ID sobre o estado mais recente da fila.
    exec 9>"${LOCK_FILE}"
    flock -n 9 || return 0

    local SNAPSHOT
    local VALID
    local IDS
    local HISTORY_TMP
    local QUEUE_TMP
    local TOTAL
    local VALID_COUNT

    SNAPSHOT="$(mktemp "${EVENT_DIR}/queue.snapshot.XXXXXX.json")"
    VALID="$(mktemp "${EVENT_DIR}/queue.valid.XXXXXX.json")"
    IDS="$(mktemp "${EVENT_DIR}/queue.ids.XXXXXX.json")"
    HISTORY_TMP="$(mktemp "${EVENT_DIR}/history.new.XXXXXX.json")"
    QUEUE_TMP="$(mktemp "${EVENT_DIR}/queue.new.XXXXXX.json")"

    cleanup()
    {
        rm -f "${SNAPSHOT}" "${VALID}" "${IDS}" "${HISTORY_TMP}" "${QUEUE_TMP}"
    }
    trap cleanup RETURN

    cp "${QUEUE_FILE}" "${SNAPSHOT}"

    TOTAL="$(jq 'length' "${SNAPSHOT}")"
    [[ "${TOTAL}" -gt 0 ]] || return 0

    # Mantém somente eventos com schema mínimo válido.
    jq '[
        .[]
        | select(
            type == "object"
            and (.id | type == "string" and length > 0)
            and (.type | type == "string" and length > 0)
            and (.category | type == "string" and length > 0)
            and (.timestamp | type == "number")
        )
    ]' "${SNAPSHOT}" > "${VALID}"

    VALID_COUNT="$(jq 'length' "${VALID}")"

    if [[ "${VALID_COUNT}" -eq 0 ]]
    then
        log "Snapshot possui ${TOTAL} evento(s), mas nenhum é válido; fila mantida para diagnóstico."
        return 0
    fi

    jq '[.[].id]' "${VALID}" > "${IDS}"

    # Consolida e deduplica pelo ID. Em caso de ID repetido, mantém
    # a versão mais recente encontrada no conjunto combinado.
    jq -s \
        --argjson limit "${DSM_EVENT_HISTORY_LIMIT}" '
        (.[0] + .[1])
        | reverse
        | unique_by(.id)
        | reverse
        | sort_by(.timestamp // 0)
        | if length > $limit then .[-$limit:] else . end
    ' "${HISTORY_FILE}" "${VALID}" > "${HISTORY_TMP}"

    jq -e 'type == "array"' "${HISTORY_TMP}" >/dev/null
    mv -f "${HISTORY_TMP}" "${HISTORY_FILE}"

    # Reabre a fila atual e remove SOMENTE IDs presentes no snapshot
    # processado. Eventos publicados enquanto o histórico era atualizado
    # permanecem na fila para a próxima iteração.
    jq --slurpfile ids "${IDS}" '
        ($ids[0]) as $processed
        | [ .[] | select((.id as $id | $processed | index($id)) == null) ]
    ' "${QUEUE_FILE}" > "${QUEUE_TMP}"

    jq -e 'type == "array"' "${QUEUE_TMP}" >/dev/null
    mv -f "${QUEUE_TMP}" "${QUEUE_FILE}"

    log "Processados ${VALID_COUNT}/${TOTAL} evento(s); histórico=$(jq 'length' "${HISTORY_FILE}") fila=$(jq 'length' "${QUEUE_FILE}")."
}

run_forever()
{
    log "Worker iniciado. interval=${DSM_EVENT_QUEUE_INTERVAL}s"

    while true
    do
        process_once || log "Falha durante processamento da fila."
        sleep "${DSM_EVENT_QUEUE_INTERVAL}"
    done
}

case "${1:-run}" in
    once)
        process_once
        ;;

    run|daemon)
        run_forever
        ;;

    *)
        echo "Uso: $0 [once|run]" >&2
        exit 2
        ;;
esac
