#!/usr/bin/env bash

# =============================================================
# DSM Game Adapter
#
# DayZ - process.sh
#
# Responsável:
# Informar como localizar o processo do jogo
#
# O Core DSM não conhece DayZ.
# =============================================================


set -Eeuo pipefail


# -------------------------------------------------------------
# Comando principal do processo
# -------------------------------------------------------------

game_process_command()
{

    echo "./DayZServer"

}



# -------------------------------------------------------------
# Validação opcional do processo
# -------------------------------------------------------------

game_process_validate()
{

    local PID="$1"


    if [ -z "$PID" ]
    then
        return 1
    fi


    if ! [[ "$PID" =~ ^[0-9]+$ ]]
    then
        return 1
    fi


    if ! kill -0 "$PID" 2>/dev/null
    then
        return 1
    fi


    local CMD

    CMD="$(ps -p "$PID" -o args= 2>/dev/null | xargs)"


    if [ -z "$CMD" ]
    then
        return 1
    fi


    if echo "$CMD" | grep -Eqi \
    "(^|/)(DayZServer_x64|DayZServer|dayzserver)( |$)"
    then

        return 0

    fi


    return 1

}



# -------------------------------------------------------------
# Busca PID
# -------------------------------------------------------------

game_process_pid()
{

    local PID


    while read -r PID
    do

        if game_process_validate "$PID"
        then

            echo "$PID"
            return 0

        fi


    done < <(
        pgrep -f "DayZServer|DayZServer_x64|dayzserver"
    )


    echo "0"

    return 1

}



# Execução direta

if [ "${BASH_SOURCE[0]}" = "$0" ]
then

    game_process_pid

fi