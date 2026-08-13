#!/bin/bash
# =============================================================
# Atualiza scheduler_state.json
# =============================================================
set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
TMP=$("$DSM_ROOT/dashboard/api/scheduler.sh" list)
echo "$TMP" > "$STATE_DIR/scheduler_state.json"
