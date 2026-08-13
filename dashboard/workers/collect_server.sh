#!/bin/bash
# =============================================================
# Atualiza server_state.json
# =============================================================
set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
TMP=$("$DSM_ROOT/dashboard/api/server.sh" status)
echo "$TMP" > "$STATE_DIR/server_state.json"
