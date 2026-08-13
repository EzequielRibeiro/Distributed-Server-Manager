#!/bin/bash

#
# DSM Runtime Dashboard API
#
# Camada única para Dashboard
#

set -e


DSM_ROOT="/opt/dsm"


case "$1" in


summary)


SERVER="$2"
GAME="$3"
INSTANCE="$4"


if [ -z "$SERVER" ] || \
   [ -z "$GAME" ] || \
   [ -z "$INSTANCE" ]
then

    echo '{"error":"missing parameters"}'
    exit 1

fi



BASE="$DSM_ROOT/runtime/resources/$SERVER/$GAME/$INSTANCE"



if [ ! -d "$BASE" ]
then

jq -n \
--arg path "$BASE" \
'
{
 "error":"resource_not_found",
 "path":$path
}
'

exit 1

fi



for file in \
server.json \
mods.json \
metrics.json \
doctor.json \
events.json \
backup.json \
instance.json

do

if [ ! -f "$BASE/$file" ]
then

echo "{}" > "$BASE/$file"

fi

done



jq \
-n \
--arg server "$SERVER" \
--arg game "$GAME" \
--arg instance "$INSTANCE" \
--slurpfile srv "$BASE/server.json" \
--slurpfile mods "$BASE/mods.json" \
--slurpfile metrics "$BASE/metrics.json" \
--slurpfile doctor "$BASE/doctor.json" \
--slurpfile events "$BASE/events.json" \
--slurpfile backup "$BASE/backup.json" \
--slurpfile instance_metadata "$BASE/instance.json" \
'
{
 "server":$server,
 "game":$game,
 "instance":$instance,

 "server_state":$srv[0],

 "mods":$mods[0],

 "metrics":$metrics[0],

 "events":$events[0],

 "backup":$backup[0],
 "instance_metadata":$instance_metadata[0]
}
'


;;


*)

echo "
Uso:

dashboard.sh summary <server> <game> <instance>

"

exit 1

;;

esac
