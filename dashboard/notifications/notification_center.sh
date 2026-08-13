#!/bin/bash
# =============================================================
# DSM Notification Center
# Módulo 11 - Dashboard Notification System
# Responsabilidades: Consumir eventos, Gerenciar fila, Registrar histórico, Sinalizar Discord Worker
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
BASE="$DSM_ROOT/dashboard/notifications"
QUEUE="$BASE/notification_queue.json"
HISTORY="$BASE/notification_history.log"
PENDING="$BASE/.discord_pending"

mkdir -p "$BASE"

# -------------------------------------------------------------
# Inicializa arquivos
# -------------------------------------------------------------
if [ ! -f "$QUEUE" ]
then
    echo "[]" > "$QUEUE"
fi

if [ ! -f "$HISTORY" ]
then
    touch "$HISTORY"
fi

# -------------------------------------------------------------
# Função: registrar histórico
# -------------------------------------------------------------
log_event() {
    local LEVEL="$1"
    local TITLE="$2"
    local MESSAGE="$3"
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $LEVEL | $TITLE | $MESSAGE" >> "$HISTORY"
}

# -------------------------------------------------------------
# Validar fila
# -------------------------------------------------------------
if ! jq empty "$QUEUE" 2>/dev/null
then
    echo "[]" > "$QUEUE"
fi

# -------------------------------------------------------------
# Verificar notificações pendentes
# -------------------------------------------------------------
TOTAL=$(jq length "$QUEUE")
if [ "$TOTAL" -eq 0 ]
then
    exit 0
fi

# -------------------------------------------------------------
# Processar notificações novas
# -------------------------------------------------------------
jq -c '.[] | select(.processed != true)' "$QUEUE" |
while read item
do
    ID=$(echo "$item" | jq -r '.id')
    LEVEL=$(echo "$item" | jq -r '.level')
    TITLE=$(echo "$item" | jq -r '.title')
    MESSAGE=$(echo "$item" | jq -r '.message')
    log_event "$LEVEL" "$TITLE" "$MESSAGE"
done

# -------------------------------------------------------------
# Marcar eventos processados
# -------------------------------------------------------------
TMP=$(mktemp)
jq 'map(if .processed == true then . else .processed=true end)' "$QUEUE" > "$TMP"
mv "$TMP" "$QUEUE"

# -------------------------------------------------------------
# Sinaliza Discord Worker
# -------------------------------------------------------------
touch "$PENDING"

# -------------------------------------------------------------
# Limpeza opcional da fila
# -------------------------------------------------------------
TMP=$(mktemp)
jq 'if length > 100 then .[-100:] else . end' "$QUEUE" > "$TMP"
mv "$TMP" "$QUEUE"

exit 0
