#!/bin/bash
# =============================================================
# monitor/events.sh - MÓDULO 04 (MONITOR)
# Sistema de eventos do DSM
# Formato: JSON Lines
# Consumido por:
# - Dashboard
# - API
# - Scheduler
# - Notification
# - Doctor
# =============================================================

LOG_MODULE="monitor"
EVENTS_FILE="${DSM_ROOT}/cache/events.log"

# =============================================================
# Inicialização
# =============================================================
events_init()
{
    mkdir -p "$(dirname "$EVENTS_FILE")"
    touch "$EVENTS_FILE"
}

# =============================================================
# Escapa JSON
# =============================================================
_events_escape()
{
    printf '%s' "$1" |
        sed \
            -e 's/\\/\\\\/g' \
            -e 's/"/\\"/g'
}

# =============================================================
# Emite evento
# Uso:
# events_emit \
#   "server.started" \
#   "Servidor iniciado"
#
# events_emit \
#   "watchdog.restart" \
#   "Tentativa 2" \
#   '{"attempt":2}'
# =============================================================
events_emit()
{
    local type="$1"
    local message="$2"
    local payload="${3:-{}}"
    local ts
    ts="$(date --iso-8601=seconds)"
    message="$(_events_escape "$message")"

    {
        flock -x 200
        printf \
'{"ts":"%s","type":"%s","message":"%s","payload":%s}\n' \
"$ts" \
"$type" \
"$message" \
"$payload"
    } 200>>"$EVENTS_FILE"

    log_debug "Evento: $type"
}

# =============================================================
# Últimos eventos (JSON)
# =============================================================
events_recent_json()
{
    local n="${1:-20}"
    [ -f "$EVENTS_FILE" ] || {
        echo "[]"
        return
    }

    tail -n "$n" "$EVENTS_FILE" |
        jq -s '.' 2>/dev/null ||
        echo "[]"
}

# =============================================================
# Últimos eventos (Terminal)
# =============================================================
events_recent()
{
    local n="${1:-20}"
    [ -f "$EVENTS_FILE" ] || {
        log_warn "Nenhum evento registrado."
        return
    }

    tail -n "$n" "$EVENTS_FILE" |
    while read -r line
    do
        local ts
        local type
        local msg
        ts="$(jq -r '.ts' <<<"$line" 2>/dev/null)"
        type="$(jq -r '.type' <<<"$line" 2>/dev/null)"
        msg="$(jq -r '.message' <<<"$line" 2>/dev/null)"

        printf "%-28s %-24s %s\n" \
            "$ts" \
            "$type" \
            "$msg"
    done
}

# =============================================================
# Rotação
# =============================================================
events_rotate()
{
    local max_mb="${1:-10}"
    [ -f "$EVENTS_FILE" ] || return 0
    local size
    size=$(( $(stat -c%s "$EVENTS_FILE") / 1024 / 1024 ))

    [ "$size" -lt "$max_mb" ] && return 0
    mv "$EVENTS_FILE" "$EVENTS_FILE.1"
    gzip -f "$EVENTS_FILE.1"
    touch "$EVENTS_FILE"
}

# =============================================================
# Limpeza
# =============================================================
events_cleanup()
{
    find "$(dirname "$EVENTS_FILE")" \
        -name "events.log*.gz" \
        -mtime +30 \
        -delete 2>/dev/null
}
