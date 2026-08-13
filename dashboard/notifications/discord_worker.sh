#!/bin/bash
# =============================================================
# DSM Discord Worker
# Módulo 11.9
# Responsabilidades: Consumir fila de notificações, Enviar Discord Webhook, Registrar envio
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
BASE="$DSM_ROOT/dashboard/notifications"
QUEUE="$BASE/notification_queue.json"
CONFIG="$DSM_ROOT/dashboard/config/discord.conf"
HISTORY="$BASE/notification_history.log"
PENDING="$BASE/.discord_pending"

if [ -f "$CONFIG" ]; then
    source "$CONFIG"
fi

if [ "$DISCORD_ENABLED" != "true" ]; then
    exit 0
fi

if [ ! -f "$PENDING" ] || [ ! -f "$QUEUE" ]; then
    exit 0
fi

jq -c '.[] | select(.sent != true)' "$QUEUE" |
while read item
do
    LEVEL=$(echo "$item" | jq -r '.level')
    TITLE=$(echo "$item" | jq -r '.title')
    MESSAGE=$(echo "$item" | jq -r '.message')
    ID=$(echo "$item" | jq -r '.id')

    PAYLOAD=$(jq -n \
    --arg title "$TITLE" \
    --arg message "$MESSAGE" \
    --arg level "$LEVEL" \
    --arg username "$DISCORD_USERNAME" \
    '{ username:$username, embeds:[{ title:$title, description:$message, fields:[{ name:"Nível", value:$level, inline:true }] }] }')

    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -H "Content-Type: application/json" -X POST -d "$PAYLOAD" "$DISCORD_WEBHOOK_URL")

    if [ "$RESPONSE" = "204" ]
    then
        echo "$(date '+%Y-%m-%d %H:%M:%S') | SENT | $ID" >> "$HISTORY"
        TMP=$(mktemp)
        jq --arg id "$ID" 'map(if .id==$id then .sent=true else . end)' "$QUEUE" > "$TMP"
        mv "$TMP" "$QUEUE"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') | ERROR | $ID HTTP:$RESPONSE" >> "$HISTORY"
    fi
done

rm -f "$PENDING"
exit 0
