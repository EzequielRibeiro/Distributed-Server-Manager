#!/bin/bash
# =============================================================
# DSM Event History Worker
#
# Move eventos:
#
# queue.json
#      |
#      v
# history.json
#
# Commit 15
# =============================================================

set -u


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

QUEUE="$DSM_ROOT/runtime/events/queue.json"
HISTORY="$DSM_ROOT/runtime/events/history.json"

MAX_HISTORY="${MAX_HISTORY:-1000}"
DSM_INTERVAL="${DSM_INTERVAL:-10}"


mkdir -p "$(dirname "$HISTORY")"



init_files()
{

    if [ ! -f "$QUEUE" ]
    then
        echo "[]" > "$QUEUE"
    fi


    if ! jq -e 'type=="array"' "$QUEUE" >/dev/null 2>&1
    then
        echo "[]" > "$QUEUE"
    fi



    if [ ! -f "$HISTORY" ]
    then
        echo "[]" > "$HISTORY"
    fi


    if ! jq -e 'type=="array"' "$HISTORY" >/dev/null 2>&1
    then
        echo "[]" > "$HISTORY"
    fi

}



persist_events()
{

    local COUNT

    COUNT=$(jq length "$QUEUE")


    if [ "$COUNT" -eq 0 ]
    then
        return
    fi



    local TMP

    TMP=$(mktemp)



    jq -s \
    --argjson max "$MAX_HISTORY" \
    '
    (
        .[0] + .[1]
    )
    |
    unique_by(.id)
    |
    sort_by(.timestamp)
    |
    reverse
    |
    .[0:$max]
    ' \
    "$HISTORY" \
    "$QUEUE" \
    > "$TMP"



    if jq empty "$TMP" >/dev/null 2>&1
    then

        mv "$TMP" "$HISTORY"

        echo "[]" > "$QUEUE"

    else

        rm -f "$TMP"

    fi

}



run()
{
    init_files
    persist_events
}



while true
do

    run

    sleep "$DSM_INTERVAL"

done