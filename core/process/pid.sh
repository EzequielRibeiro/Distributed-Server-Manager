#!/usr/bin/env bash

#
# Capivara DSM
#
# Process PID Manager
#

set -Eeuo pipefail


pid_file()
{
    local INSTANCE_PATH="$1"

    echo "${INSTANCE_PATH}/runtime/process.pid"
}


process_pid()
{
    local INSTANCE_PATH="$1"

    local PID_FILE

    PID_FILE="$(pid_file "${INSTANCE_PATH}")"


    [[ -f "${PID_FILE}" ]] || return 0


    cat "${PID_FILE}"
}


process_pid_exists()
{
    local PID="$1"

    [[ -n "${PID}" ]] || return 1


    kill -0 "${PID}" 2>/dev/null
}


process_pid_validate()
{
    local PID="$1"


    if process_pid_exists "${PID}"
    then
        return 0
    fi


    return 1
}


export -f pid_file
export -f process_pid
export -f process_pid_exists
export -f process_pid_validate
