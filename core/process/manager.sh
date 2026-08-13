#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Process Manager Library
#
# Biblioteca responsável pelo gerenciamento
# do ciclo de vida das instâncias.
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/config/runtime.sh"
source "${DSM_ROOT}/core/runtime/context.sh"

source "${DSM_ROOT}/core/process/process.sh"
source "${DSM_ROOT}/core/process/pid.sh"
source "${DSM_ROOT}/core/process/tree.sh"

# =============================================================
# Resolve informações da instância
# =============================================================

manager_load_instance() {

    local INSTANCE_PATH

    INSTANCE_PATH="$(get_instance_path)"

    local INSTANCE_CONF="${INSTANCE_PATH}/instance.conf"

    [[ -f "${INSTANCE_CONF}" ]] || {
        echo "Configuração da instância não encontrada:"
        echo "${INSTANCE_CONF}"
        return 1
    }

    source "${INSTANCE_CONF}"

    export INSTANCE_PATH
    export INSTANCE_CONF

}

# =============================================================
# Log
# =============================================================

manager_log() {

    mkdir -p "${DSM_LOG_DIR}"

    echo "$(date '+%F %T') $*" \
        >> "${DSM_LOG_DIR}/process-manager.log"

}

# =============================================================
# Start
# =============================================================

manager_start() {

    manager_load_instance || return 1

    manager_log "START ${DSM_INSTANCE_ID}"

    process_start \
        "${INSTANCE_PATH}" \
        "${WORKING_DIR}/${EXECUTABLE}"

}

# =============================================================
# Stop
# =============================================================

manager_stop() {

    manager_load_instance || return 1

    manager_log "STOP ${DSM_INSTANCE_ID}"

    process_stop "${INSTANCE_PATH}"

}

# =============================================================
# Restart
# =============================================================

manager_restart() {

    manager_load_instance || return 1

    manager_log "RESTART ${DSM_INSTANCE_ID}"

    process_restart "${INSTANCE_PATH}"

}

# =============================================================
# Status
# =============================================================

manager_status() {

    manager_load_instance || return 1

    process_status "${INSTANCE_PATH}"

}

# =============================================================
# PID
# =============================================================

manager_pid() {

    manager_load_instance || return 1

    process_pid "${INSTANCE_PATH}"

}

# =============================================================
# Health
# =============================================================

manager_health() {

    manager_load_instance || return 1

    if [[ "$(process_status "${INSTANCE_PATH}")" == "online" ]]
    then
        echo "healthy"
    else
        echo "unhealthy"
        return 1
    fi

}

# =============================================================
# Exports
# =============================================================

export -f manager_load_instance
export -f manager_log

export -f manager_start
export -f manager_stop
export -f manager_restart
export -f manager_status
export -f manager_pid
export -f manager_health