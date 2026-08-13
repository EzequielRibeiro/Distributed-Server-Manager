#!/bin/sh
#
# Generic Event Provider
#


provider_name()
{
    echo generic
}


provider_events()
{
cat <<EOF
SERVER_START
SERVER_STOP
SERVER_CRASH
EOF
}