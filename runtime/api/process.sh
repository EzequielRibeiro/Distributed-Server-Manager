#!/bin/sh
#
# DSM Universal Runtime
# Process API
#

runtime_process_name()
{
    runtime_driver_call driver_process
}


runtime_process_exists()
{
    local process

    process=$(runtime_process_name)

    [ -z "$process" ] && return 1

    pgrep -f "$process" >/dev/null 2>&1
}


runtime_process_pid()
{
    local process

    process=$(runtime_process_name)

    pgrep -f "$process" | head -n 1
}