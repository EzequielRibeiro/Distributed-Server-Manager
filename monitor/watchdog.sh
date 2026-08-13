#!/bin/bash
# =============================================================
# monitor/watchdog.sh - MÓDULO 04 (MONITOR)
# Detecta queda do DayZ e executa recuperação automática.
# Fonte oficial: server_status()
# =============================================================

LOG_MODULE="monitor"
WATCHDOG_STATE_FILE="${DSM_ROOT}/cache/watchdog.state"
WATCHDOG_MAX_ATTEMPTS=5
WATCHDOG_COOLDOWN_SECONDS=300

_watchdog_read_attempts()
{
    [ -f "$WATCHDOG_STATE_FILE" ] || {
        echo "0 0"
        return
    }
    cat "$WATCHDOG_STATE_FILE"
}

_watchdog_write_attempts()
{
    mkdir -p "$(dirname "$WATCHDOG_STATE_FILE")"
    echo "$1 $2" > "$WATCHDOG_STATE_FILE"
}

watchdog_reset()
{
    _watchdog_write_attempts 0 0
}

watchdog_check()
{
    # =========================================================
    # Verificação oficial do servidor
    # =========================================================
    local STATUS
    STATUS="$(server_status)"

    if [ "$STATUS" = "ONLINE" ]
    then
        watchdog_reset
        return 0
    fi

    local attempts
    local last_ts
    local now
    read -r attempts last_ts <<< "$(_watchdog_read_attempts)"

    attempts="${attempts:-0}"
    last_ts="${last_ts:-0}"

    [[ "$attempts" =~ ^[0-9]+$ ]] || attempts=0
    [[ "$last_ts" =~ ^[0-9]+$ ]] || last_ts=0

    now=$(date +%s)

    if [ "$attempts" -ge "$WATCHDOG_MAX_ATTEMPTS" ]
    then
        if [ $((now-last_ts)) -lt "$WATCHDOG_COOLDOWN_SECONDS" ]
        then
            log_error \
            "Watchdog: limite atingido aguardando cooldown"
            events_emit \
            "watchdog.cooldown" \
            "Limite de recuperação atingido"
            return 1
        fi
        attempts=0
    fi

    local next_attempt
    next_attempt=$((attempts+1))

    log_warn \
    "Watchdog: servidor $STATUS - tentativa ${next_attempt}/${WATCHDOG_MAX_ATTEMPTS}"

    events_emit \
    "watchdog.restart_attempt" \
    "Tentativa ${next_attempt} de recuperação"

    if ! start_run
    then
        log_error \
        "Watchdog: falha ao executar start_run"
        _watchdog_write_attempts \
        "$next_attempt" \
        "$now"
        return 1
    fi

    _watchdog_write_attempts \
    "$next_attempt" \
    "$now"

    sleep 5

    if [ "$(server_status)" = "ONLINE" ]
    then
        log_ok \
        "Watchdog: servidor recuperado"

        events_emit \
        "watchdog.recovered" \
        "Servidor voltou online"

        notify_dispatch \
        "server_recovered" \
        "{\"instance\":\"$INSTANCE_NAME\"}"

        watchdog_reset
        return 0
    else
        log_error \
        "Watchdog: recuperação falhou"
        events_emit \
        "watchdog.restart_failed" \
        "Tentativa ${next_attempt} falhou"

        notify_dispatch \
        "server_down" \
        "{\"instance\":\"$INSTANCE_NAME\",\"attempt\":${next_attempt}}"
        return 1
    fi
}
