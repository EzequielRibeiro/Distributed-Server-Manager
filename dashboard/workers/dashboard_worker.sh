#!/bin/bash
# =============================================================
# DSM Dashboard Worker
# dashboard_worker.sh
# Atualiza: dashboard/state/dashboard_state.json
# Consolida todos os estados produzidos pelos workers em um único arquivo utilizado pelo Dashboard Web.
# Intervalo: 5 segundos
# =============================================================

set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
OUTPUT="$STATE_DIR/dashboard_state.json"

mkdir -p "$STATE_DIR"

# -------------------------------------------------------------
# Arquivos de estado
# -------------------------------------------------------------
SERVER_STATE="$STATE_DIR/server_state.json"
METRICS_STATE="$STATE_DIR/metrics_state.json"
MONITOR_STATE="$STATE_DIR/monitor_state.json"
ALERTS_STATE="$STATE_DIR/alerts_state.json"
SCHEDULER_STATE="$STATE_DIR/scheduler_state.json"
EVENTS_STATE="$STATE_DIR/events_state.json"

# -------------------------------------------------------------
# Inicializa arquivos inexistentes
# -------------------------------------------------------------
for f in "$SERVER_STATE" "$METRICS_STATE" "$MONITOR_STATE" "$ALERTS_STATE" "$SCHEDULER_STATE" "$EVENTS_STATE"
do
    [ -f "$f" ] || echo "{}" > "$f"
done

# -------------------------------------------------------------
# Loop principal
# -------------------------------------------------------------
while true
do
    TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
    jq -n \
        --arg ts "$TIMESTAMP" \
        --slurpfile server "$SERVER_STATE" \
        --slurpfile metrics "$METRICS_STATE" \
        --slurpfile monitor "$MONITOR_STATE" \
        --slurpfile alerts "$ALERTS_STATE" \
        --slurpfile scheduler "$SCHEDULER_STATE" \
        --slurpfile events "$EVENTS_STATE" \
'
{
    timestamp: $ts,
    version: "DSM Dashboard v1.3.0",
    server: ($server[0] // {}),
    metrics: ($metrics[0] // {}),
    monitor: ($monitor[0] // {}),
    alerts: ($alerts[0] // {}),
    scheduler: ($scheduler[0] // {}),
    events: ($events[0] // {})
}
' > "$OUTPUT.tmp"
    mv "$OUTPUT.tmp" "$OUTPUT"
    sleep 5
done
