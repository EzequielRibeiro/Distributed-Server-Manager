#!/bin/bash

#
# DSM Universal Event Collector
# Commit 14
#


set -e


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


source "$DSM_ROOT/core/bootstrap.sh"

source "$DSM_ROOT/core/lib/runtime.sh"


runtime_init



EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"


STATE_DIR="$DSM_ROOT/runtime/events/state"


mkdir -p "$STATE_DIR"



send_event()
{

CATEGORY="$1"

TYPE="$2"

MESSAGE="$3"


"$EVENT_MANAGER" \
"$CATEGORY" \
"$TYPE" \
"$MESSAGE"

}



collect_server_state()
{


SERVER=$(runtime_get server)



STATUS=$(echo "$SERVER" | jq -r '.status // "unknown"')

PID=$(echo "$SERVER" | jq -r '.pid // 0')



case "$STATUS" in


online)

send_event \
server \
SERVER_START \
"Servidor iniciado PID=$PID"

;;



offline)

send_event \
server \
SERVER_STOP \
"Servidor parado"

;;



*)

send_event \
server \
SERVER_STATUS_CHANGE \
"Estado=$STATUS"

;;

esac


}



main()
{

collect_server_state


}


main "$@"