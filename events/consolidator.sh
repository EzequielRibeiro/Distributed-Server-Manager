#!/bin/bash
# =============================================================
# DSM Event Consolidator
# Commit 16
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

EVENT_HISTORY="$DSM_ROOT/runtime/events/history.json"

mkdir -p "$(dirname "$EVENT_HISTORY")"

[ -f "$EVENT_HISTORY" ] || echo "[]" > "$EVENT_HISTORY"

add_event()
{
    local EVENT="$1"

    local TMP

    TMP=$(mktemp)

    jq ". + [$EVENT]" \
        "$EVENT_HISTORY" \
        > "$TMP"

    mv "$TMP" "$EVENT_HISTORY"
}

list_events()
{
    jq '.' "$EVENT_HISTORY"
}

case "$1" in

add)

add_event "$2"

;;

list)

list_events

;;

*)

echo "Uso:
consolidator.sh add JSON
consolidator.sh list"

;;

esac