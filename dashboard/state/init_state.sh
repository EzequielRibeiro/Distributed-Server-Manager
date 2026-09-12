#!/bin/bash
# =============================================================
# DSM Dashboard
# init_state.sh
# Inicializa somente estado operacional transitório ainda atual.
# Eventos, alertas, telemetria, runtime e saúde são autoritativos nas
# plataformas/repositórios atuais, não em projeções JSON legadas.
# =============================================================

set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"

mkdir -p "$STATE_DIR"

FILES=(
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

# Projeções aposentadas não são preservadas durante reinstalação/atualização.
rm -f \
    "$STATE_DIR/dashboard_state.json" \
    "$STATE_DIR/server_state.json" \
    "$STATE_DIR/metrics_state.json" \
    "$STATE_DIR/monitor_state.json" \
    "$STATE_DIR/alerts_state.json" \
    "$STATE_DIR/events_state.json"

echo
echo "Dashboard State transitório inicializado com sucesso."
