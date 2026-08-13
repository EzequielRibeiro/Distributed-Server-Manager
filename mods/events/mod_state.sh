#!/bin/bash

# =============================================================
# DSM Mod Runtime State
# Commit 15
#
# Integração Universal Event Platform
# =============================================================


set -e


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


STATE="$DSM_ROOT/runtime/mods/state.json"


EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"



SERVER="${DSM_SERVER_ID:-server01}"
GAME="${DSM_GAME:-dayz}"
INSTANCE="${DSM_INSTANCE:-survival01}"



init()
{

mkdir -p "$(dirname "$STATE")"


[ -f "$STATE" ] ||
echo "{}" > "$STATE"

}



emit_event()
{

TYPE="$1"
MESSAGE="$2"


"$EVENT_MANAGER" \
mod \
"$TYPE" \
"$MESSAGE" \
"$SERVER" \
"$GAME" \
"$INSTANCE"

}



update()
{

init


MOD="$1"

STATUS="$2"



tmp=$(mktemp)



jq \
--arg mod "$MOD" \
--arg status "$STATUS" \
--argjson updated "$(date +%s)" \
'
.[ $mod ] =
{
    "status": $status,
    "updated": $updated
}
' \
"$STATE" \
> "$tmp"



mv "$tmp" "$STATE"


}



list()
{

init

cat "$STATE"

}



case "$1" in


update)

update "$2" "$3"

;;


list)

list

;;


*)

echo "
mod_state.sh

update MOD STATUS

list
"

;;

esac