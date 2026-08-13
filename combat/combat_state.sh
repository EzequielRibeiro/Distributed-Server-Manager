#!/bin/bash

# =============================================================
# DSM Combat Runtime State
# Estado de combate.
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


STATE="$DSM_ROOT/runtime/combat/state.json"



init()
{

mkdir -p "$(dirname "$STATE")"


[ -f "$STATE" ] ||
echo "{}" > "$STATE"

}



kill()
{

init


PLAYER="$1"



tmp=$(mktemp)



jq \
"
.[$PLAYER].kills += 1
" \
"$STATE" \
> "$tmp"



mv "$tmp" "$STATE"

}



death()
{

init


PLAYER="$1"



tmp=$(mktemp)



jq \
"
.[$PLAYER].deaths += 1
" \
"$STATE" \
> "$tmp"



mv "$tmp" "$STATE"

}



case "$1" in


kill)

kill "$2"

;;


death)

death "$2"

;;


*)

echo "
combat_state.sh

kill jogador

death jogador

"

;;

esac