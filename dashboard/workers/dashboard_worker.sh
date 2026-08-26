#!/bin/bash
# =============================================================
# DSM Dashboard Worker
# Consolida apenas estado operacional transitório da Dashboard.
# Eventos, alertas e auditoria são exclusivamente persistidos no database.
# =============================================================

set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
OUTPUT="$STATE_DIR/dashboard_state.json"

mkdir -p "$STATE_DIR"

SERVER_STATE="$STATE_DIR/server_state.json"
METRICS_STATE="$STATE_DIR/metrics_state.json"
MONITOR_STATE="$STATE_DIR/monitor_state.json"
SCHEDULER_STATE="$STATE_DIR/scheduler_state.json"

for f in "$SERVER_STATE" "$METRICS_STATE" "$MONITOR_STATE" "$SCHEDULER_STATE"
do
    [ -f "$f" ] || echo "{}" > "$f"
done

while true
do
    TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
    jq -n \
        --arg ts "$TIMESTAMP" \
        --slurpfile server "$SERVER_STATE" \
        --slurpfile metrics "$METRICS_STATE" \
        --slurpfile monitor "$MONITOR_STATE" \
        --slurpfile scheduler "$SCHEDULER_STATE" \
'
{
    timestamp: $ts,
    version: "DSM Dashboard v1.3.0",
    server: ($server[0] // {}),
    metrics: ($metrics[0] // {}),
    monitor: ($monitor[0] // {}),
    scheduler: ($scheduler[0] // {})
}
' > "$OUTPUT.tmp"
    mv "$OUTPUT.tmp" "$OUTPUT"
    sleep 5
done
