#!/bin/sh
#
# DSM Universal Runtime
# Driver Manager
#

DSM_DRIVER_NAME=""
DSM_DRIVER_FILE=""


runtime_driver_load()
{
    local game="$1"

    local driver="$RUNTIME_DIR/drivers/${game}.sh"

    [ -f "$driver" ] || \
        driver="$RUNTIME_DIR/drivers/generic.sh"


    . "$driver"


    DSM_DRIVER_NAME="$game"
    DSM_DRIVER_FILE="$driver"


    driver_init


    driver_validate || return 1


    driver_manifest | runtime_manifest
}


runtime_driver_name()
{
    echo "$DSM_DRIVER_NAME"
}


runtime_driver_call()
{
    local fn="$1"

    shift


    type "$fn" >/dev/null 2>&1 || return 1


    "$fn" "$@"
}