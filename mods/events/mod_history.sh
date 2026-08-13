#!/bin/bash

# =============================================================
# DSM Mod History
# Commit 15
#
# Compatibilidade Legacy
#
# Agora integrado ao Universal Event Platform
#
# =============================================================


set -e


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"



add()
{

EVENT="$1"



if ! echo "$EVENT" | jq empty >/dev/null 2>&1
then
    echo "JSON inválido"
    exit 1
fi



TYPE=$(echo "$EVENT" | jq -r '.type // "MOD_EVENT"')


MESSAGE=$(echo "$EVENT" | \
jq -r '.data.raw // .data.message // "Mod event"')



SERVER=$(echo "$EVENT" | \
jq -r '.resource.server // ""')


GAME=$(echo "$EVENT" | \
jq -r '.resource.game // ""')


INSTANCE=$(echo "$EVENT" | \
jq -r '.resource.instance // ""')



"$EVENT_MANAGER" \
mod \
"$TYPE" \
"$MESSAGE" \
"$SERVER" \
"$GAME" \
"$INSTANCE"

}



list()
{

echo "O histórico de Mods agora está centralizado em:"


echo "$DSM_ROOT/runtime/events/history.json"


jq '
[
 .[]
 | select(.category=="mod")
]
' \
"$DSM_ROOT/runtime/events/history.json"

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
DSM Mod History

Uso:

mod_history.sh add JSON

mod_history.sh list

"

;;


esac