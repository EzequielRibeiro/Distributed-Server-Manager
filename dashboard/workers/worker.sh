#!/usr/bin/env bash

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

WORKERS_DIR="${DSM_ROOT}/dashboard/workers"

LOG="${DSM_ROOT}/logs/dashboard_worker.log"


log()
{
    echo "$(date '+%F %T') $*" >> "$LOG"
}


start_worker()
{
    local WORKER="$1"

    if [ -x "${WORKERS_DIR}/${WORKER}" ]
    then
        log "Iniciando ${WORKER}"

        bash "${WORKERS_DIR}/${WORKER}" daemon \
        >> "$LOG" 2>&1 &

    else
        log "Worker inexistente: ${WORKER}"
    fi
}


start_python_worker()
{
    local WORKER="$1"

    if [ -f "${WORKERS_DIR}/${WORKER}" ]
    then
        log "Iniciando ${WORKER}"

        python3 "${WORKERS_DIR}/${WORKER}" \
        >> "$LOG" 2>&1 &

    else
        log "Worker inexistente: ${WORKER}"
    fi
}


main()
{

    mkdir -p "$(dirname "$LOG")"


    start_worker dashboard_worker.sh

    start_worker server_worker.sh

    start_worker metrics_worker.sh

    start_worker scheduler_worker.sh

    start_worker events_worker.sh

    start_worker monitor_worker.sh

    start_worker mods_worker.sh

    start_worker alerts_worker.sh

    start_worker backup_worker.sh

    # Mantém inventory/heartbeat do Agent local em Nodes hybrid.
    # Em Nodes controller o processo permanece inerte até a promoção.
    start_python_worker hybrid_agent_worker.py


    while true
    do
        sleep 60
    done

}


main
