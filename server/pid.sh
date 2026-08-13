#!/usr/bin/env bash

# =============================================================
# DSM Server - PID Manager
#
# Responsável:
# Localizar PID do servidor do jogo atual
#
# Arquitetura:
#
# Core não conhece jogos.
# Cada jogo fornece seu próprio adapter.
#
# =============================================================

set -euo pipefail


# -------------------------------------------------------------
# Validar DSM
# -------------------------------------------------------------

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# -------------------------------------------------------------
# Carregar contexto
# -------------------------------------------------------------

source "${DSM_ROOT}/core/runtime_context.sh"


# -------------------------------------------------------------
# Retorna comando do processo do jogo
# -------------------------------------------------------------

game_process()
{

    local GAME

    GAME="$(runtime_game | tr '[:upper:]' '[:lower:]')"


    local ADAPTER

    ADAPTER="${DSM_ROOT}/games/${GAME}/process.sh"


    #
    # Adapter oficial do jogo
    #

    if [ -f "${ADAPTER}" ]
    then

        source "${ADAPTER}"


        if declare -F game_process_command >/dev/null
        then

            game_process_command

            return 0

        fi

    fi



    #
    # Compatibilidade temporária
    #
    # Remover após migração dos adapters
    #

    case "$GAME" in


        dayz)

            echo "./DayZServer"

        ;;


        arma3)

            echo "./arma3server"

        ;;


        *)

            echo ""

        ;;

    esac

}



# -------------------------------------------------------------
# Obtém PID
# -------------------------------------------------------------

server_pid()
{

    local PROCESS

    PROCESS="$(game_process)"



    if [ -z "$PROCESS" ]
    then

        echo "0"

        return 1

    fi



    local PID


    PID=$(pgrep -f "$PROCESS" | head -n1 || true)



    if [ -n "$PID" ]
    then

        echo "$PID"

        return 0

    fi



    echo "0"

    return 1

}



# -------------------------------------------------------------
# Compatibilidade
# -------------------------------------------------------------

pid_get()
{
    server_pid
}



export -f game_process
export -f server_pid
export -f pid_get



# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------

if [ "${BASH_SOURCE[0]}" = "$0" ]
then

    server_pid

fi