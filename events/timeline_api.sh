#!/bin/bash


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


FILE="$DSM_ROOT/runtime/events/history.json"


LIMIT="${1:-50}"



if [ ! -f "$FILE" ]
then

cat <<EOF
{
"events":[],
"total":0,
"last_event":null
}
EOF

exit

fi



EVENTS=$(jq \
--argjson limit "$LIMIT" \
'
sort_by(.timestamp)
| reverse
| .[0:$limit]
' \
"$FILE"
)



TOTAL=$(echo "$EVENTS" | jq length)



LAST=$(echo "$EVENTS" | jq '.[0] // null')



jq -n \
--argjson events "$EVENTS" \
--argjson total "$TOTAL" \
--argjson last "$LAST" \
'
{
events:$events,
total:$total,
last_event:$last
}
'