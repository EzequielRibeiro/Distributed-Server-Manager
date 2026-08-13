#!/bin/bash

# =============================================================
# DSM Combat Engine
# Motor principal.
# =============================================================


set -e


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


PARSER="$DSM_ROOT/combat/combat_parser.py"


EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"



process()
{

LINE="$1"



EVENT=$(echo "$LINE" | \
python3 "$PARSER")



TYPE=$(echo "$EVENT" | jq -r '.type')



MESSAGE=$(echo "$EVENT" | \
jq -r '.data.raw')



case "$TYPE" in


PLAYER_KILL)


"$EVENT_MANAGER" \
combat \
PLAYER_KILL \
"$MESSAGE"


;;



PLAYER_DEATH)


"$EVENT_MANAGER" \
combat \
PLAYER_DEATH \
"$MESSAGE"


;;



PLAYER_SUICIDE)


"$EVENT_MANAGER" \
combat \
PLAYER_SUICIDE \
"$MESSAGE"


;;


esac


}



case "$1" in


test)

process "$2"

;;


*)

echo "

DSM Combat Engine


Uso:


combat_engine.sh test \"linha RPT\"


"

;;


esac