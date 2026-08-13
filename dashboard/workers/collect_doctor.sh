#!/bin/bash
# =============================================================
# Atualiza doctor_state.json
# =============================================================
set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
TMP=$("$DSM_ROOT/dashboard/api/doctor.sh" quick)
echo "$TMP" > "$STATE_DIR/doctor_state.json"
