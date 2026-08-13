#!/bin/bash

#
# DSM Universal Event Dispatcher
#


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


QUEUE="$DSM_ROOT/runtime/events/queue.json"

HISTORY="$DSM_ROOT/runtime/events/history.json"


mkdir -p "$(dirname "$QUEUE")"



init()
{

[ -f "$QUEUE" ] || echo "[]" > "$QUEUE"

[ -f "$HISTORY" ] || echo "[]" > "$HISTORY"

}



dispatch()
{

init


COUNT=$(jq length "$QUEUE")


if [ "$COUNT" -eq 0 ]
then
    exit 0
fi



EVENTS=$(cat "$QUEUE")



tmp=$(mktemp)



jq \
". + $EVENTS" \
"$HISTORY" \
> "$tmp"



mv "$tmp" "$HISTORY"



echo "[]" > "$QUEUE"



}



dispatch