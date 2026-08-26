#!/bin/bash
# =============================================================
# monitor/monitor.sh - MÓDULO 04 (MONITOR)
# Agregador do sistema de monitoramento DSM.
# Integra:
# - events
# - resources
# - health
# - watchdog
# - recovery
# Fonte oficial:
# server_status()
# server_pid()
# =============================================================

LOG_MODULE="monitor"

# =============================================================
# Ambiente
# =============================================================
if [ -z "$DSM_ROOT" ]; then
    DSM_ROOT="/opt/dsm"
fi

DSM_MONITOR_DIR="${DSM_ROOT}/monitor"

# =============================================================
# Carrega módulos
# O SERVER já vem pelo bootstrap.
# =============================================================
source "$DSM_MONITOR_DIR/events.sh"
source "$DSM_MONITOR_DIR/resources.sh"
source "$DSM_MONITOR_DIR/health.sh"
source "$DSM_MONITOR_DIR/watchdog.sh"
source "$DSM_MONITOR_DIR/recovery.sh"

# =============================================================
# Configuração
# =============================================================
MONITOR_INTERVAL_SECONDS="${MONITOR_INTERVAL_SECONDS:-60}"

# =============================================================
# Inicialização
# =============================================================
monitor_init()
{
    events_init
    mkdir -p "${DSM_ROOT}/cache"
}

# =============================================================
# Vínculo dos Agents
# O sweep é best-effort: indisponibilidade temporária do backend não pode
# interromper o monitor principal.
# =============================================================
agent_link_sweep()
{
    local sweep="$DSM_MONITOR_DIR/agent_link_sweep.py"
    if [ -f "$sweep" ]; then
        DSM_ROOT="$DSM_ROOT" python3 "$sweep" >/dev/null 2>&1 || true
    fi
}

# =============================================================
# Ciclo único
# Usado pelo daemon e testes
# =============================================================
monitor_cycle()
{
    local health
    health="$(health_check)"
    case "$health" in
        HEALTHY)
            ;;
        CRITICAL)
            watchdog_check
            ;;
        WARNING)
            log_warn \
            "Monitor detectou condição degradada"
            ;;
    esac
    recovery_run
    agent_link_sweep
    notify_flush 2>/dev/null || true
}

# =============================================================
# Daemon
# =============================================================
monitor_daemon()
{
    monitor_init
    if ! lock_acquire "monitor"
    then
        log_error \
        "Já existe um monitor DSM executando"
        return 1
    fi
    trap '
        lock_release "monitor"
        exit 0
    ' EXIT
    log_ok \
    "Monitor daemon iniciado (${MONITOR_INTERVAL_SECONDS}s)"
    while true
    do
        monitor_cycle
        sleep "$MONITOR_INTERVAL_SECONDS"
    done
}

# =============================================================
# Dashboard CLI
# =============================================================
# =============================================================
# Dashboard CLI
# =============================================================
monitor_dashboard()
{
    local refresh="${1:-5}"
    local metrics_file="${DSM_ROOT}/runtime/metrics.json"

    while true
    do
        clear
        section "DSM SERVER MONITOR"
        echo

        server_status
        echo

        if [ -f "$metrics_file" ]; then

            local cpu memory disk disk_free

            cpu=$(jq -r '.cpu.host_pct // "-"' "$metrics_file")
            memory=$(jq -r '.memory.dayz_pct // "-"' "$metrics_file")
            disk=$(jq -r '.disk.used_pct // "-"' "$metrics_file")
            disk_free=$(jq -r '.disk.free_human // "-"' "$metrics_file")

            echo "CPU host........ ${cpu}%"
            echo "RAM DayZ........ ${memory}%"
            echo "Disco usado..... ${disk}% (${disk_free} livres)"

        else

            # Compatibilidade com versões anteriores
            echo "CPU processo.... $(resources_process_cpu)%"
            echo "RAM processo.... $(resources_process_ram_mb) MB"
            echo "Disco livre..... $(resources_disk_free_pct)% ($(resources_disk_free_human))"

        fi

        echo
        echo "Atualização ${refresh}s - CTRL+C encerra"

        sleep "$refresh"
    done
}

# =============================================================
# Status completo
# =============================================================
monitor_status()
{
    section "DSM STATUS"
    server_status
    echo
    health_summary
    echo
    echo "Eventos recentes:"
    events_recent 10
}

# =============================================================
# JSON Dashboard/API
# =============================================================
monitor_status_json()
{
    local metrics_file="${DSM_ROOT}/runtime/metrics.json"
    local metrics='{}'

    if [ -f "$metrics_file" ]; then
        metrics="$(cat "$metrics_file")"
    fi

    jq -n \
        --argjson server "$(server_status_json)" \
        --argjson resources "$(resources_json)" \
        --argjson metrics "$metrics" \
        --arg health "$(health_status 2>/dev/null)" \
        --argjson alerts "$(health_alerts_json 2>/dev/null || echo '[]')" \
        '
        {
            server: $server,
            resources: $resources,
            metrics: $metrics,
            health: $health,
            alerts: $alerts
        }
        '
}


monitor_runtime_metrics()
{
    local metrics_file

    metrics_file="${DSM_ROOT}/runtime/metrics.json"

    if [ ! -f "$metrics_file" ]; then
        return 1
    fi

    jq -r '
    {
        cpu: .cpu.host_pct,
        memory: .memory.dayz_pct,
        disk: .disk.used_pct
    }
    ' "$metrics_file"
}
