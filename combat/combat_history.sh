#!/bin/bash

# =============================================================
# DSM Combat History
# Commit 12
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


FILE="$DSM_ROOT/runtime/combat/history.json"



init()
{

mkdir -p "$(dirname "$FILE")"


[ -f "$FILE" ] ||
echo "[]" > "$FILE"

}



add()
{

init


EVENT="$1"


tmp=$(mktemp)


jq \
". + [$EVENT]" \
"$FILE" \
> "$tmp"


mv "$tmp" "$FILE"

}



list()
{

init

jq '.' "$FILE"

}



case "$1" in


add)

add "$2"

;;


list)

list

;;


*)

echo "

Combat History

add JSON

list

"

;;

esac