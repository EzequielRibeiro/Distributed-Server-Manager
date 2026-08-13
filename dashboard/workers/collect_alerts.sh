#!/bin/bash
# =============================================================
# Atualiza alerts_state.json
# =============================================================
set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
TMP=$("$DSM_ROOT/dashboard/api/alerts.sh")
echo "$TMP" > "$STATE_DIR/alerts_state.json"
