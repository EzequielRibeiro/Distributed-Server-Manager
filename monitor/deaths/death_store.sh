#!/bin/bash
# =============================================================
# DSM Death Store
# Persistência de mortes DayZ
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

STATE_FILE="$DSM_ROOT/dashboard/state/death_events.json"

MAX_EVENTS=100


save_death_event()
{

    local message="$1"
    local timestamp="$2"
    local killer="$3"
    local victim="$4"
    local cause="$5"


    mkdir -p "$(dirname "$STATE_FILE")"


    if [ ! -f "$STATE_FILE" ]; then

        echo '{"total":0,"events":[]}' > "$STATE_FILE"

    fi


    local id

    id=$(echo "${timestamp}${victim}${cause}" | md5sum | awk '{print $1}')


    jq \
    --arg id "$id" \
    --arg message "$message" \
    --arg timestamp "$timestamp" \
    --arg killer "$killer" \
    --arg victim "$victim" \
    --arg cause "$cause" '

    if any(.events[]; .id == $id)

    then .

    else

        .events += [{
            "id":$id,
            "timestamp":$timestamp,
            "killer":$killer,
            "victim":$victim,
            "cause":$cause,
            "message":$message
        }]

        | .events = .events[-100:]
        | .total = (.events|length)

    end

    ' \
    "$STATE_FILE" > "$STATE_FILE.tmp"


    mv "$STATE_FILE.tmp" "$STATE_FILE"

}