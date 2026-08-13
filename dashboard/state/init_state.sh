#!/bin/bash
# =============================================================
# DSM Dashboard
# init_state.sh
# Inicializa os arquivos de estado do Dashboard
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
    alerts
    doctor
    scheduler
    events
)

for file in "${FILES[@]}"; do
    STATE_FILE="$STATE_DIR/${file}_state.json"
    if [ ! -f "$STATE_FILE" ]; then
        printf '{}\n' > "$STATE_FILE"
        chmod 664 "$STATE_FILE"
        echo "Criado: $(basename "$STATE_FILE")"
    fi
done

echo
echo "Dashboard State inicializado com sucesso."
