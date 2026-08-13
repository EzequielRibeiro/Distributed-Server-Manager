#!/bin/bash

# =============================================================
# DSM Player Event Engine
# Motor principal de eventos de jogadores.
# =============================================================


set -e


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


PARSER="$DSM_ROOT/player/player_parser.py"


EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"


process()
{


LINE="$1"



EVENT=$(echo "$LINE" | \
python3 "$PARSER")



TYPE=$(echo "$EVENT" | jq -r '.type')



case "$TYPE" in


PLAYER_JOIN)

"$EVENT_MANAGER" \
player \
PLAYER_JOIN \
"$(echo "$EVENT" | jq -r '.data.raw')"

;;



PLAYER_LEAVE)

"$EVENT_MANAGER" \
player \
PLAYER_LEAVE \
"$(echo "$EVENT" | jq -r '.data.raw')"

;;



PLAYER_DEATH)

"$EVENT_MANAGER" \
player \
PLAYER_DEATH \
"$(echo "$EVENT" | jq -r '.data.raw')"

;;



PLAYER_SUICIDE)

"$EVENT_MANAGER" \
player \
PLAYER_SUICIDE \
"$(echo "$EVENT" | jq -r '.data.raw')"

;;


esac


}



case "$1" in


test)

process "$2"

;;


*)

echo "
DSM Player Engine

Uso:

player_engine.sh test \"linha do RPT\"

"

;;


esac