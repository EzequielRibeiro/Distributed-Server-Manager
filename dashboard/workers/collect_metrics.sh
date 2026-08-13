#!/bin/bash
# =============================================================
# Atualiza metrics_state.json
# =============================================================
set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
TMP=$("$DSM_ROOT/dashboard/api/metrics.sh" status)
echo "$TMP" > "$STATE_DIR/metrics_state.json"
