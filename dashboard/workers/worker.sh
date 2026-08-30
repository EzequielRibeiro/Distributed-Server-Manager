#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
WORKERS_DIR="${DSM_ROOT}/dashboard/workers"
LOG="${DSM_ROOT}/logs/dashboard_worker.log"
PIDS=()
WORKER_NAMES=()

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

stop_children(){
    local PID
    for PID in "${PIDS[@]:-}"; do
        kill "${PID}" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}

supervise_workers(){
    local STATUS=0
    set +e
    wait -n "${PIDS[@]}"
    STATUS=$?
    set -e
    log "Worker filho encerrou inesperadamente (status=${STATUS}); reiniciando grupo via systemd"
    return 1
}

main(){
    mkdir -p "$(dirname "$LOG")"
    trap stop_children EXIT INT TERM

    # Workers legados server_worker.sh e backup_worker.sh não pertencem mais
    # ao runtime consolidado. As funções atuais vivem nas plataformas de
    # eventos/runtime e backup do Capivara.
    start_worker dashboard_worker.sh
    start_worker metrics_worker.sh
    start_worker scheduler_worker.sh
    start_worker monitor_worker.sh
    start_python_worker automation_worker.py
    start_python_worker hybrid_agent_worker.py

    supervise_workers
}

main
