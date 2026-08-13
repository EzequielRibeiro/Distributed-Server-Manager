#!/usr/bin/env bash


source "/opt/dsm/config/runtime.sh"


runtime_launcher()
{
    echo "$(runtime_instance_path)/launcher.sh"
}


runtime_instance_path()
{
    get_instance_path
}


runtime_start()
{
    "$(runtime_launcher)" start
}


runtime_stop()
{
    "$(runtime_launcher)" stop
}


runtime_restart()
{
    "$(runtime_launcher)" restart
}


runtime_status()
{
    "$(runtime_launcher)" status
}


runtime_pid()
{
    "$(runtime_launcher)" pid
}


export -f runtime_launcher
export -f runtime_instance_path
export -f runtime_start
export -f runtime_stop
export -f runtime_restart
export -f runtime_status
export -f runtime_pid