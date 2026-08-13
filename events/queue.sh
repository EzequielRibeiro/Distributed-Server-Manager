#!/bin/bash

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

QUEUE="$DSM_ROOT/runtime/events/queue.json"


mkdir -p "$(dirname "$QUEUE")"


init()
{

if [ ! -f "$QUEUE" ]
then

echo "[]" > "$QUEUE"

fi

}



push()
{

init


if [[ -p /dev/stdin ]]
then
    EVENT="$(cat)"
else
    EVENT="$1"
fi


tmp=$(mktemp)


jq \
". + [$EVENT]" \
"$QUEUE" \
> "$tmp"


mv "$tmp" "$QUEUE"

}



pop()
{

init


jq '
.[0]
' "$QUEUE"


tmp=$(mktemp)


jq '
.[1:]
' "$QUEUE" \
> "$tmp"


mv "$tmp" "$QUEUE"

}



case "$1" in

push)

push "$2"

;;

pop)

pop

;;

*)

echo "
DSM Event Queue

Uso:

queue.sh push JSON

queue.sh pop

"

;;

esac