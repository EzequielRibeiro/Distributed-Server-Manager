#!/bin/bash
# =============================================================
# DSM Dashboard Worker
# monitor_worker.sh
# Atualiza: dashboard/state/monitor_state.json
# Responsável por gerar o estado geral de saúde do servidor
# Intervalo: 5 segundos
# =============================================================

set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
OUTPUT="$STATE_DIR/monitor_state.json"

mkdir -p "$STATE_DIR"
# shellcheck source=/dev/null
source "$DSM_ROOT/core/bootstrap.sh"

while true
do
    TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
    STATUS="OFFLINE"
    ONLINE=false
    CPU=0
    RAM=0
    DISK=0

    # ---------------------------------------------------------
    # Processo DayZ
    # ---------------------------------------------------------
    PID="$(pid_get 2>/dev/null || true)"

    if [ -n "${PID:-}" ] && [ -d "/proc/$PID" ]
    then
        ONLINE=true
        STATUS="OK"
        CPU=$(ps -p "$PID" -o %cpu= | tr -d ' ')
        CPU="${CPU:-0}"
        RAM=$(awk '/VmRSS/ {print int($2/1024)}' "/proc/$PID/status" 2>/dev/null)
        RAM="${RAM:-0}"
    fi

    # ---------------------------------------------------------
    # Disco
    # ---------------------------------------------------------
    DISK_USED=$(df -P "$DSM_ROOT" | awk 'NR==2{print $5}' | tr -d '%')
    DISK_FREE=$((100-DISK_USED))

    # ---------------------------------------------------------
    # Saúde geral
    # ---------------------------------------------------------
    if [ "$ONLINE" = true ]
    then
        if (( DISK_FREE < 10 ))
        then
            STATUS="CRITICO"
        elif (( ${CPU%.*} >= 90 ))
        then
            STATUS="CRITICO"
        elif (( DISK_FREE < 20 ))
        then
            STATUS="DEGRADADO"
        elif (( ${CPU%.*} >= 70 ))
        then
            STATUS="DEGRADADO"
        fi
    fi

   jq -n \
       --arg ts "$TIMESTAMP" \
       --arg status "$STATUS" \
       --argjson online "$ONLINE" \
       --argjson cpu "$CPU" \
       --argjson ram "$RAM" \
       --argjson disk "$DISK_FREE" \
   '{
       timestamp: $ts,
       online: $online,
       health: $status,
       resources: {
           cpu_pct: $cpu,
           ram_mb: $ram,
           disk_free_pct: $disk,
           disk_free_human: (($disk|tostring)+"%")
       }
   }' > "$OUTPUT.tmp"
   mv "$OUTPUT.tmp" "$OUTPUT"
   sleep 5
done
