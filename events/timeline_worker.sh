#!/bin/bash


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


OUTPUT="$DSM_ROOT/dashboard/state/events_state.json"


API="$DSM_ROOT/events/timeline_api.sh"



mkdir -p "$(dirname "$OUTPUT")"



if [ -x "$API" ]
then

"$API" 100 > "$OUTPUT"


else


cat > "$OUTPUT" <<EOF
{
"events":[],
"total":0,
"last_event":null
}
EOF


fi