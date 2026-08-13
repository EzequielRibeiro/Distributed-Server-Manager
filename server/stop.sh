#!/usr/bin/env bash

# =============================================================
# DSM Server - Stop
#
# Responsável:
# Solicitar parada da instância atual
#
# Arquitetura:
# Core não conhece jogos.
# Cada jogo fornece seu runtime adapter.
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# -------------------------------------------------------------
# Carregar contexto
# -------------------------------------------------------------

source "${DSM_ROOT}/core/runtime/context.sh"


# =============================================================
# Publisher
# =============================================================

source "${DSM_ROOT}/core/runtime/publisher.sh"


# -------------------------------------------------------------
# Carregar adapter do jogo
# -------------------------------------------------------------

load_game_runtime()
{

    local GAME

    GAME="$(runtime_game | tr '[:upper:]' '[:lower:]')"


    local RUNTIME

    RUNTIME="${DSM_ROOT}/games/${GAME}/runtime.sh"


    if [ ! -f "${RUNTIME}" ]
    then
        echo "Runtime não encontrado:"
        echo "${RUNTIME}"
        return 1
    fi


    source "${RUNTIME}"

}


# -------------------------------------------------------------
# Stop
# -------------------------------------------------------------

server_stop()
{

    load_game_runtime || return 1


    if declare -F runtime_stop >/dev/null
    then

        echo "Parando:"
        echo "Game: $(runtime_game)"
        echo "Instance: $(runtime_instance)"

        runtime_stop

        runtime_stop || {
            echo "DEBUG: runtime_stop retornou erro" >> /opt/dsm/logs/server_stop.log
        }

        sleep 3

        echo "DEBUG: executando publisher" >> /opt/dsm/logs/server_stop.log

        publish_server_state || {
            echo "DEBUG: publisher falhou" >> /opt/dsm/logs/server_stop.log
        }

    else

        echo "runtime_stop não implementado para:"
        echo "$(runtime_game)"

        return 1

    fi

}


# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------

if [ "${BASH_SOURCE[0]}" = "$0" ]
then

    server_stop

fi