#!/bin/bash
# =============================================================
# dashboard/dashboard.sh - MÓDULO 09 (DASHBOARD)
# Controlador principal da Dashboard Web DSM
# Responsável:
#   - iniciar dashboard
#   - parar dashboard
#   - verificar status
#   - executar em foreground (systemd)
# Servidor: dashboard/server.py
# DSM Version: 1.2.0
# =============================================================

LOG_MODULE="dashboard"

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

DASHBOARD_PID_DIR="${DSM_ROOT}/tmp"
DASHBOARD_PID_FILE="${DASHBOARD_PID_DIR}/dashboard.pid"

DASHBOARD_PORT="${DASHBOARD_PORT:-8080}"

DASHBOARD_SERVER="${DSM_ROOT}/dashboard/server.py"

DASHBOARD_LOG="${DSM_ROOT}/logs/dashboard.log"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
dashboard_init()
{
    mkdir -p "$DASHBOARD_PID_DIR"
    mkdir -p "$(dirname "$DASHBOARD_LOG")"
}

# -------------------------------------------------------------
# Verifica se dashboard está executando
# -------------------------------------------------------------
dashboard_running()
{
    if [ ! -f "$DASHBOARD_PID_FILE" ]
    then
        return 1
    fi

    local PID
    PID=$(cat "$DASHBOARD_PID_FILE" 2>/dev/null)

    if [ -z "$PID" ]
    then
        return 1
    fi

    kill -0 "$PID" 2>/dev/null
}

# -------------------------------------------------------------
# Executar em primeiro plano
# Usado pelo systemd
# -------------------------------------------------------------
dashboard_run_foreground()
{
    dashboard_init
    export DASHBOARD_PORT
    exec python3 "$DASHBOARD_SERVER"
}

# -------------------------------------------------------------
# Iniciar Dashboard
# -------------------------------------------------------------
dashboard_start()
{
    dashboard_init

    if dashboard_running
    then
        log_warn "A dashboard já está rodando (PID $(cat "$DASHBOARD_PID_FILE"))"
        return 0
    fi

    if [ ! -f "$DASHBOARD_SERVER" ]
    then
        log_error "Servidor Dashboard não encontrado: $DASHBOARD_SERVER"
        return 1
    fi

    export DASHBOARD_PORT

    nohup python3 "$DASHBOARD_SERVER" \
        >> "$DASHBOARD_LOG" 2>&1 &

    echo $! > "$DASHBOARD_PID_FILE"

    sleep 1

    if dashboard_running
    then
        log_ok "Dashboard iniciada na porta $DASHBOARD_PORT (PID $(cat "$DASHBOARD_PID_FILE"))"
        return 0
    else
        log_error "A dashboard não iniciou - veja $DASHBOARD_LOG"
        rm -f "$DASHBOARD_PID_FILE"
        return 1
    fi
}

# -------------------------------------------------------------
# Parar Dashboard
# -------------------------------------------------------------
dashboard_stop()
{
    dashboard_init

    if ! dashboard_running
    then
        log_warn "A dashboard não está rodando"
        rm -f "$DASHBOARD_PID_FILE"
        return 0
    fi

    local PID
    PID=$(cat "$DASHBOARD_PID_FILE")

    if kill -0 "$PID" 2>/dev/null
    then
        kill "$PID"
        sleep 1
    fi

    rm -f "$DASHBOARD_PID_FILE"

    log_ok "Dashboard parada"
}

# -------------------------------------------------------------
# Status
# -------------------------------------------------------------
dashboard_status()
{
    dashboard_init

    if dashboard_running
    then
        log_ok "Dashboard rodando (PID $(cat "$DASHBOARD_PID_FILE"), porta $DASHBOARD_PORT)"
    else
        log_warn "Dashboard não está rodando"
    fi
}
