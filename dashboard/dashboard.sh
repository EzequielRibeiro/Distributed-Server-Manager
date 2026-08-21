#!/bin/bash
# =============================================================
# dashboard/dashboard.sh - Dashboard launcher compatibility
# Canonical composition entrypoint: dashboard/server_part13.py
# =============================================================
LOG_MODULE="dashboard"
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DASHBOARD_PID_DIR="${DSM_ROOT}/tmp";DASHBOARD_PID_FILE="${DASHBOARD_PID_DIR}/dashboard.pid";DASHBOARD_PORT="${DASHBOARD_PORT:-8080}"
DASHBOARD_SERVER="${DSM_ROOT}/dashboard/server_part13.py";DASHBOARD_LOG="${DSM_ROOT}/logs/dashboard.log"
dashboard_init(){ mkdir -p "$DASHBOARD_PID_DIR" "$(dirname "$DASHBOARD_LOG")"; }
dashboard_running(){ [[ -f "$DASHBOARD_PID_FILE" ]] || return 1; local PID;PID=$(cat "$DASHBOARD_PID_FILE" 2>/dev/null);[[ -n "$PID" ]] || return 1;kill -0 "$PID" 2>/dev/null; }
dashboard_run_foreground(){ dashboard_init;export DASHBOARD_PORT;exec python3 "$DASHBOARD_SERVER"; }
dashboard_start(){ dashboard_init;if dashboard_running;then log_warn "A dashboard já está rodando (PID $(cat "$DASHBOARD_PID_FILE"))";return 0;fi;[[ -f "$DASHBOARD_SERVER" ]]||{ log_error "Servidor Dashboard não encontrado: $DASHBOARD_SERVER";return 1; };export DASHBOARD_PORT;nohup python3 "$DASHBOARD_SERVER" >>"$DASHBOARD_LOG" 2>&1 & echo $! >"$DASHBOARD_PID_FILE";sleep 1;if dashboard_running;then log_ok "Dashboard iniciada na porta $DASHBOARD_PORT (PID $(cat "$DASHBOARD_PID_FILE"))";return 0;fi;log_error "A dashboard não iniciou - veja $DASHBOARD_LOG";rm -f "$DASHBOARD_PID_FILE";return 1; }
dashboard_stop(){ dashboard_init;if ! dashboard_running;then log_warn "A dashboard não está rodando";rm -f "$DASHBOARD_PID_FILE";return 0;fi;local PID;PID=$(cat "$DASHBOARD_PID_FILE");kill "$PID" 2>/dev/null||true;sleep 1;rm -f "$DASHBOARD_PID_FILE";log_ok "Dashboard parada"; }
dashboard_status(){ dashboard_init;if dashboard_running;then log_ok "Dashboard rodando (PID $(cat "$DASHBOARD_PID_FILE"), porta $DASHBOARD_PORT)";else log_warn "Dashboard não está rodando";fi; }
