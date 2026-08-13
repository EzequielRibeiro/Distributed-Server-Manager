#!/bin/bash
# =============================================================
# monitor/recovery.sh - MÓDULO 04 (MONITOR)
# Recuperação de condições degradadas:
# - Disco baixo
# - RAM baixa
# Não reinicia servidor.
# Watchdog controla processo DayZ.
# =============================================================

if [ -z "$DSM_ROOT" ]; then
    DSM_ROOT="/opt/dsm"
fi

source "$DSM_ROOT/core/logger.sh"
source "$DSM_ROOT/monitor/events.sh"
source "$DSM_ROOT/monitor/resources.sh"
source "$DSM_ROOT/notification/notify.sh"

LOG_MODULE="monitor"
HEALTH_DISK_WARN_PCT="${HEALTH_DISK_WARN_PCT:-15}"
HEALTH_RAM_WARN_PCT="${HEALTH_RAM_WARN_PCT:-10}"
RECOVERY_ALERT_STATE_DIR="${DSM_ROOT}/cache/alerts"
