#!/bin/bash
# =============================================================
# DSM Dashboard
# init_state.sh
# Inicializa somente estado operacional transitório do Dashboard.
# Eventos, alertas e auditoria duráveis pertencem exclusivamente ao database.
# =============================================================

set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"

mkdir -p "$STATE_DIR"

FILES=(
    dashboard
    server
    metrics
    monitor
    doctor
    scheduler
)

for file in "${FILES[@]}"; do
    STATE_FILE="$STATE_DIR/${file}_state.json"
    if [ ! -f "$STATE_FILE" ]; then
        printf '{}\n' > "$STATE_FILE"
        chmod 664 "$STATE_FILE"
        echo "Criado: $(basename "$STATE_FILE")"
    fi
done

# Não preserve projeções duráveis antigas em JSON durante reinstalação.
rm -f \
    "$STATE_DIR/alerts_state.json" \
    "$STATE_DIR/events_state.json"

echo
echo "Dashboard State transitório inicializado com sucesso."
