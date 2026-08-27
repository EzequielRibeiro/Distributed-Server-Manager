#!/usr/bin/env bash
# =============================================================
# monitor/health.sh - MÓDULO 04 (MONITOR)
# DSM Monitor Health Check
# Fonte única: server_status()
# Retornos:
# 0 - HEALTHY
# 1 - CRITICAL
# 2 - WARNING
# 3 - UNKNOWN
# =============================================================

LOG_MODULE="monitor"
HEALTH_STATE_FILE="${DSM_ROOT}/cache/health.state"

health_check()
{
    log_info "Executando health check"
    local STATUS
    STATUS="$(server_status)"

    case "$STATUS" in
        ONLINE)
            echo "HEALTHY"
            events_emit "SERVER_HEALTHY" "Servidor online" 2>/dev/null || true
            echo "ONLINE" > "$HEALTH_STATE_FILE"
            return 0
            ;;
        OFFLINE)
            echo "CRITICAL"
            events_emit "SERVER_OFFLINE" "Servidor parado" 2>/dev/null || true
            echo "OFFLINE" > "$HEALTH_STATE_FILE"
            return 1
            ;;
        "PROCESSO INVÁLIDO")
            echo "WARNING"
            events_emit "SERVER_INVALID_PROCESS" "PID inválido ou processo inesperado" 2>/dev/null || true
            echo "INVALID" > "$HEALTH_STATE_FILE"
            return 2
            ;;
        *)
            echo "UNKNOWN"
            echo "UNKNOWN" > "$HEALTH_STATE_FILE"
            return 3
            ;;
    esac
}

health_status_json()
{
    local STATUS
    STATUS="$(server_status)"

    case "$STATUS" in
        ONLINE)
            cat <<EOF
{
    "health":"healthy",
    "server":"online",
    "pid":"$(server_pid)"
}
EOF
            ;;
        OFFLINE)
            cat <<EOF
{
    "health":"critical",
    "server":"offline",
    "pid":null
}
EOF
            ;;
        "PROCESSO INVÁLIDO")
            cat <<EOF
{
    "health":"warning",
    "server":"invalid_process",
    "pid":"$(server_pid)"
}
EOF
            ;;
        *)
            cat <<EOF
{
    "health":"unknown",
    "server":"unknown",
    "pid":null
}
EOF
            ;;
    esac
}
