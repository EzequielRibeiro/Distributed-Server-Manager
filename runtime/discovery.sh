#!/bin/sh
#
# Runtime Discovery
#

runtime_discover()
{
    runtime_detect_game

    runtime_detect_server
}

runtime_detect_game()
{
    [ -n "$DSM_GAME" ] && return

    DSM_GAME="dayz"
}

runtime_detect_server()
{
    [ -n "$DSM_SERVER" ] && return

    DSM_SERVER="server01"
}