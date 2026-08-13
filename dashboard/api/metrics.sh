#!/bin/bash
# =============================================================
# dashboard/api/metrics.sh - DSM Dashboard API Metrics
#
# Expõe as métricas da DSM Metrics Engine para o Dashboard Web
# Exposes DSM Metrics Engine metrics to the Web Dashboard
#
# Uso | Usage: metrics.sh status, health
# =============================================================

DSM_ROOT="${DSM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
if [[ -s "${DSM_ROOT}/version" ]]
then
    DSM_VERSION=$(tr -d '\r\n' <"${DSM_ROOT}/version")
else
    DSM_VERSION="unknown"
fi
METRICS_CORE="$DSM_ROOT/monitor/metrics/metrics.sh"

# =============================================================
# Carregar Metrics Engine | Load Metrics Engine
# =============================================================
load_metrics() {
    if [ ! -f "$METRICS_CORE" ]; then
        echo '{"error":"DSM Metrics Engine não encontrada | not found"}'
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$METRICS_CORE"
}

# =============================================================
# Status das métricas | Metrics status
# =============================================================
metrics_status() {
    load_metrics
    metrics_json
}

# =============================================================
# Health simplificado para API | Simplified Health for API
# =============================================================
metrics_health() {
    load_metrics
    cat <<EOF
{
    "engine":"DSM Metrics Engine",
    "version":"${DSM_VERSION}",
    "status":"online"
}
EOF
}

# =============================================================
# Router
# =============================================================
action="${1:-status}"
case "$action" in
    status)
        metrics_status
        ;;
    health)
        metrics_health
        ;;
    *)
        echo "{\"error\":\"ação desconhecida | unknown action: $action\"}"
        exit 1
        ;;
esac
