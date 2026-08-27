#!/usr/bin/env bash
# =============================================================
# MÓDULO 02 (SERVER)
# Agregador do módulo Server nativo do Capivara.
#
# Ordem:
# pid -> process -> validate -> status -> start -> stop -> restart
# =============================================================

if [ "${DSM_SERVER_LOADED:-0}" = "1" ]; then
    return 0
fi

DSM_SERVER_LOADED=1

if [ -z "${DSM_ROOT:-}" ]; then
    DSM_ROOT="/opt/dsm"
fi

DSM_SERVER_DIR="${DSM_ROOT}/server"

source "$DSM_SERVER_DIR/pid.sh"
source "$DSM_SERVER_DIR/process.sh"
source "$DSM_SERVER_DIR/validate.sh"
source "$DSM_SERVER_DIR/status.sh"
source "$DSM_SERVER_DIR/start.sh"
source "$DSM_SERVER_DIR/stop.sh"
source "$DSM_SERVER_DIR/restart.sh"
