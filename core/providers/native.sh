#!/bin/bash


provider_pid()
{
    pgrep -f "./DayZServer" | tail -1
}


provider_status()
{

    local PID

    PID="$(provider_pid)"

    if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null
    then
        echo "ONLINE"
    else
        echo "OFFLINE"
    fi

}


provider_start()
{

    echo "Native Provider"

    game_start

}


provider_stop()
{

    local PID

    PID="$(provider_pid)"

    if [[ -z "${PID}" ]]
    then
        echo "Servidor não encontrado."
        return 1
    fi


    kill "${PID}"

}


provider_restart()
{

    provider_stop

    sleep 5

    provider_start

}


provider_logs()
{

    echo "Logs:"
    echo "${SERVERFILES_PATH}/profiles"

}


provider_health()
{

    provider_status

}