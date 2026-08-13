#!/bin/bash
# =============================================================
# monitor/metrics/metrics.sh - DSM Metrics Engine v1.1.0
# Core agregador de métricas do DSM
# Responsável por:
#   - carregar coletores
#   - consolidar informações
#   - gerar JSON único
# =============================================================

DSM_METRICS_DIR="${DSM_ROOT}/monitor/metrics"
LOG_MODULE="metrics"

# =============================================================
# Carregamento dos módulos
# =============================================================
load_metric_module()
{
    local module="$1"
    if [ -f "${DSM_METRICS_DIR}/${module}" ]; then
        # shellcheck source=/dev/null
        source "${DSM_METRICS_DIR}/${module}"
    fi
}

load_metric_module "cpu.sh"
load_metric_module "memory.sh"
load_metric_module "disk.sh"
load_metric_module "network.sh"
load_metric_module "system.sh"
load_metric_module "temperature.sh"

# =============================================================
# Timestamp da coleta
# =============================================================
metrics_timestamp()
{
    date +"%Y-%m-%d %H:%M:%S"
}

# =============================================================
# Versão da Engine
# =============================================================
metrics_version()
{
    echo "1.1.0"
}

# =============================================================
# JSON PRINCIPAL
# =============================================================
metrics_json()
{
cat <<EOF
{
    "engine": "DSM Metrics Engine",
    "version": "$(metrics_version)",
    "timestamp": "$(metrics_timestamp)",

    "cpu":
    $(metrics_cpu_json 2>/dev/null || echo '{}'),

    "memory":
    $(metrics_memory_json 2>/dev/null || echo '{}'),

    "disk":
    $(metrics_disk_json 2>/dev/null || echo '{}'),

    "network":
    $(metrics_network_json 2>/dev/null || echo '{}'),

    "system":
    $(metrics_system_json 2>/dev/null || echo '{}'),

    "temperature":
    $(metrics_temperature_json 2>/dev/null || echo '{}')
}
EOF
}

# =============================================================
# Alias compatibilidade
# Usado pelo Dashboard
# =============================================================
monitor_metrics_json()
{
    metrics_json
}
