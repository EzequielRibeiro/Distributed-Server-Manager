#!/bin/sh
#
# DayZ Event Provider
#


provider_name()
{
    echo dayz
}


provider_events()
{
cat <<EOF
SERVER_START
SERVER_STOP
SERVER_CRASH
PLAYER_JOIN
PLAYER_LEAVE
PLAYER_DEATH
EOF
}


dayz_parse_log()
{
    line="$1"


    case "$line" in

    *"Player"*"killed"*)

        echo PLAYER_DEATH
        ;;


    *"Server started"*)

        echo SERVER_START
        ;;


    esac
}