#!/bin/bash

# =============================================================
# DSM DayZ Event Parser v2.0
# Commit 10.2
#
# Player + Combat Integration
# =============================================================


set -e


DSM_ROOT="/opt/dsm"


DAYZ_PROFILE="/home/mine/steamcmd/serverfiles/profiles"


OUTPUT="$DSM_ROOT/dashboard/state/death_events.json"


EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"



RPT=$(ls -t "$DAYZ_PROFILE"/*.RPT 2>/dev/null | head -1)



if [ -z "$RPT" ]

then

exit 0

fi



grep -Ei \
"killed|died|suicide" \
"$RPT" |
tail -50 |
while read -r line

do



case "$line" in



*"suicide"*)

"$EVENT_MANAGER" \
combat \
PLAYER_SUICIDE \
"$line"

;;



*"killed"*)


"$EVENT_MANAGER" \
combat \
PLAYER_KILL \
"$line"


;;


*"died"*)


"$EVENT_MANAGER" \
combat \
PLAYER_DEATH \
"$line"


;;


esac


done



python3 <<PYTHON

import json
import time


data={

"updated_at":int(time.time()),

"source":"dayz_parser",

"status":"processed"

}


with open(
"$OUTPUT",
"w"
) as f:

 json.dump(
 data,
 f,
 indent=4
 )

PYTHON