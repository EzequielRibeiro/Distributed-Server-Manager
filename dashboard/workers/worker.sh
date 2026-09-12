#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
WORKERS_DIR="${DSM_ROOT}/dashboard/workers"
LOG="${DSM_ROOT}/logs/dashboard_worker.log"
PIDS=()
WORKER_NAMES=()
STOP_REQUESTED=0

log(){ echo "$(date '+%F %T') $*" >> "$LOG"; }

register_worker(){
    local WORKER="$1"
    local PID="$2"
    WORKER_NAMES+=("${WORKER}")
    PIDS+=("${PID}")
}

start_worker(){
    local WORKER="$1"
    if [[ ! -x "${WORKERS_DIR}/${WORKER}" ]]; then
        log "Worker obrigatório inexistente ou não executável: ${WORKER}"
        return 1
    fi
    log "Iniciando ${WORKER}"
    bash "${WORKERS_DIR}/${WORKER}" daemon >> "$LOG" 2>&1 &
    register_worker "${WORKER}" "$!"
}

start_python_worker(){
    local WORKER="$1"
    if [[ ! -f "${WORKERS_DIR}/${WORKER}" ]]; then
        log "Worker obrigatório inexistente: ${WORKER}"
        return 1
    fi
    log "Iniciando ${WORKER}"
    python3 "${WORKERS_DIR}/${WORKER}" >> "$LOG" 2>&1 &
    register_worker "${WORKER}" "$!"
}

start_python_worker_with_env(){
    local WORKER="$1"
    shift
    if [[ ! -f "${WORKERS_DIR}/${WORKER}" ]]; then
        log "Worker obrigatório inexistente: ${WORKER}"
        return 1
    fi
    log "Iniciando ${WORKER}"
    env "$@" python3 "${WORKERS_DIR}/${WORKER}" >> "$LOG" 2>&1 &
    register_worker "${WORKER}" "$!"
}

stop_children(){
    local PID
    for PID in "${PIDS[@]:-}"; do
        kill "${PID}" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}

request_stop(){
    STOP_REQUESTED=1
    log "Shutdown solicitado; encerrando workers filhos"
    stop_children
}

supervise_workers(){
    local STATUS=0

    set +e
    wait -n "${PIDS[@]}"
    STATUS=$?
    set -e

    if [[ "${STOP_REQUESTED}" -eq 1 ]]; then
        log "Shutdown controlado concluído"
        return 0
    fi

    log "Worker filho encerrou inesperadamente (status=${STATUS}); reiniciando grupo via systemd"
    return 1
}

main(){
    mkdir -p "$(dirname "$LOG")"
    trap stop_children EXIT
    trap request_stop INT TERM

    start_worker scheduler_worker.sh
    start_python_worker automation_worker.py
    start_python_worker_with_env hybrid_agent_worker.py \
        "CAPIVARA_AGENT_MODE=hybrid" \
        "CAPIVARA_DSM_ROOT=${DSM_ROOT}"
    start_python_worker hybrid_customer_workspace_worker.py

    supervise_workers
}

main
