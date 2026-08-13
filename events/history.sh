#!/bin/sh
#
# ==============================================================================
# DSM Event History
# ==============================================================================


EVENT_HISTORY="/opt/dsm/events/state/timeline.json"


history_add()
{
    event="$1"

    echo "$event" \
    >> "$EVENT_HISTORY"
}


history_list()
{
    cat "$EVENT_HISTORY"
}