#!/bin/sh
#
# DSM Universal Runtime
# DayZ Driver
#

driver_init()
{
    return 0
}


driver_validate()
{
    [ -d "$SERVER_DIR" ]
}


driver_manifest()
{
cat <<EOF

[game]

id=dayz
name=DayZ
engine=Enfusion


[server]

process=DayZServer
executable=DayZServer


[directories]

server=$SERVER_DIR
logs=$SERVER_DIR/profiles
profiles=$SERVER_DIR/profiles
mods=$SERVER_DIR/mods
backup=$SERVER_DIR


[events]

provider=dayz


[features]

mods=true
backup=true
events=true
workshop=true
battleye=true


[driver]

name=dayz
version=1.0

EOF
}


driver_process()
{
    echo "DayZServer"
}


driver_backup()
{
    runtime_get directories backup
}


driver_events()
{
    echo "dayz"
}