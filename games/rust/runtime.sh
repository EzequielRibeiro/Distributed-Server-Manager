#!/usr/bin/env bash
#
# Capivara DSM
#
# Rust Runtime Adapter
#

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


source "${DSM_ROOT}/config/runtime.sh"



runtime_instance_path()
{
    get_instance_path
}



runtime_launcher()
{
    echo "$(runtime_instance_path)/launcher.sh"
}



runtime_start()
{

echo "Iniciando Rust"
echo "Instance: ${DSM_INSTANCE_ID}"


"$(runtime_launcher)" start

}



runtime_stop()
{

echo "Parando Rust"


"$(runtime_launcher)" stop

}



runtime_restart()
{

runtime_stop

sleep 5

runtime_start

}



runtime_status()
{

"$(runtime_launcher)" status

}



runtime_pid()
{

local PID_FILE

PID_FILE="$(runtime_instance_path)/runtime/process.pid"


[[ -f "${PID_FILE}" ]] && cat "${PID_FILE}"

}



export -f runtime_start
export -f runtime_stop
export -f runtime_restart
export -f runtime_status
export -f runtime_pid