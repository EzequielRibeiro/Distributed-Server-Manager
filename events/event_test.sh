#!/bin/bash
# =============================================================
# DSM Event Core Test
# Commit 10.2
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"


if [ ! -f "$EVENT_MANAGER" ]
then

echo "Event Manager não encontrado"

exit 1

fi



case "$1" in


server)

"$EVENT_MANAGER" \
server \
SERVER_TEST \
"Teste de evento servidor"


;;


player)

"$EVENT_MANAGER" \
player \
PLAYER_TEST \
"Teste de jogador"


;;


combat)

"$EVENT_MANAGER" \
combat \
COMBAT_TEST \
"Teste de combate"


;;


admin)

"$EVENT_MANAGER" \
admin \
ADMIN_TEST \
"Teste auditoria"


;;


*)

echo "
DSM Event Test

Uso:

event_test.sh server

event_test.sh player

event_test.sh combat

event_test.sh admin

"

;;


esac