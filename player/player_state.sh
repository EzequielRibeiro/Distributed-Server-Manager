#!/bin/bash

# =============================================================
# DSM Player Runtime State
# Controlar jogadores ativos
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


STATE="$DSM_ROOT/runtime/player/state.json"



init()
{

mkdir -p \
"$(dirname "$STATE")"



if [ ! -f "$STATE" ]

then

echo "{}" > "$STATE"

fi

}



add()
{

init


PLAYER="$1"



tmp=$(mktemp)



jq \
". + {\"$PLAYER\": {\"online\":true,\"join\":$(date +%s)}}" \
"$STATE" \
> "$tmp"



mv "$tmp" "$STATE"

}



remove()
{

init


PLAYER="$1"


tmp=$(mktemp)



jq \
"del(.\"$PLAYER\")" \
"$STATE" \
> "$tmp"



mv "$tmp" "$STATE"

}



case "$1" in


add)

add "$2"

;;


remove)

remove "$2"

;;


*)

cat <<EOF

Player State

Uso:

player_state.sh add jogador

player_state.sh remove jogador

EOF

;;

esac