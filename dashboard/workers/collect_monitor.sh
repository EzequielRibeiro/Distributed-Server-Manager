#!/bin/bash
# =============================================================
# Atualiza monitor_state.json
# =============================================================
set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
TMP=$("$DSM_ROOT/dashboard/api/monitor.sh" status)
echo "$TMP" > "$STATE_DIR/monitor_state.json"
