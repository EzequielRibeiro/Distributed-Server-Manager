#!/usr/bin/env bash

DSM_ROOT="/opt/dsm"

source "${DSM_ROOT}/config/runtime.sh"

source "${DSM_ROOT}/core/process/manager.sh"


INSTANCE_PATH="$(get_instance_path)"


case "$1" in


start)

    process_start \
    "${INSTANCE_PATH}" \
    "${INSTANCE_PATH}/serverfiles/DayZServer_x64"

;;


stop)

    process_stop "${INSTANCE_PATH}"

;;


restart)

    process_restart "${INSTANCE_PATH}"

;;


status)

    process_status "${INSTANCE_PATH}"

;;


pid)

    process_pid "${INSTANCE_PATH}"

;;


*)

echo "Uso:"
echo "$0 start|stop|restart|status|pid"

;;

esac