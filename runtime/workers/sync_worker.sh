#!/bin/bash

set -e

DSM_ROOT="/opt/dsm"

RUNTIME="$DSM_ROOT/runtime"

STATE="$RUNTIME/state"

RESOURCES="$RUNTIME/resources"


source "${DSM_ROOT}/core/runtime_context.sh"

SERVER="$(runtime_host)"
GAME="$(runtime_game)"
INSTANCE="$(runtime_instance)"


SOURCE="$STATE/$SERVER/$GAME/$INSTANCE"

TARGET="$RESOURCES/$SERVER/$GAME/$INSTANCE"


mkdir -p "$TARGET"


sync_file()
{
local source="$1"
local target="$2"


if [ -f "$source" ]
then
    cp "$source" "$target"
fi

}


sync_server()
{
sync_file \
"$SOURCE/server.json" \
"$TARGET/server.json"
}


sync_metrics()
{
sync_file \
"$SOURCE/metrics.json" \
"$TARGET/metrics.json"
}


sync_doctor()
{
sync_file \
"$SOURCE/doctor.json" \
"$TARGET/doctor.json"
}


sync_events()
{
sync_file \
"$SOURCE/events.json" \
"$TARGET/events.json"
}


sync_mods()
{
sync_file \
"$SOURCE/mods.json" \
"$TARGET/mods.json"
}


sync_backup()
{
sync_file \
"$SOURCE/backup.json" \
"$TARGET/backup.json"
}

sync_instance()
{
sync_file \
"$SOURCE/instance.json" \
"$TARGET/instance.json"
}


sync_all()
{

sync_server
sync_metrics
sync_doctor
sync_events
sync_mods
sync_backup
sync_instance

echo "[OK] Runtime sync atualizado"

}


case "${1:-all}" in

all)
sync_all
;;

metrics)
sync_metrics
;;

doctor)
sync_doctor
;;

server)
sync_server
;;

*)
echo "Uso:"
echo " sync_worker.sh all"
echo " sync_worker.sh metrics"
echo " sync_worker.sh doctor"
;;

esac
