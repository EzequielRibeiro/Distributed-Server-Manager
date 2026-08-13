#!/bin/sh
#
# DSM Universal Runtime
# Generic Driver
#

driver_init()
{
    return 0
}


driver_validate()
{
    return 0
}


driver_manifest()
{
cat <<EOF

[game]

id=generic
name=Generic Game
engine=unknown


[server]

process=


[features]

mods=false
backup=false
events=false


[driver]

name=generic
version=1.0

EOF
}


driver_process()
{
    runtime_get server process
}


driver_backup()
{
    runtime_get directories backup
}


driver_events()
{
    echo ""
}
