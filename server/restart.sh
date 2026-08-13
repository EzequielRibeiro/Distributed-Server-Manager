#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Server Restart Module
#
# Responsável:
#
# Reiniciar a instância atual do jogo
#
# Arquitetura:
# Core não conhece jogos.
# Usa Game Runtime Adapter.
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"



# =============================================================
# Context
# =============================================================

source "${DSM_ROOT}/core/runtime/context.sh"

# =============================================================
# Publisher
# =============================================================

source "${DSM_ROOT}/core/runtime/publisher.sh"

# =============================================================
# Runtime Loader
# =============================================================

load_game_runtime()
{

    local GAME

    GAME="$(runtime_game | tr '[:upper:]' '[:lower:]')"


    local RUNTIME

    RUNTIME="${DSM_ROOT}/games/${GAME}/runtime.sh"


    if [[ ! -f "${RUNTIME}" ]]
    then
        echo "Runtime do jogo não encontrado:"
        echo "${RUNTIME}"
        return 1
    fi


    source "${RUNTIME}"

}


# =============================================================
# Restart
# =============================================================

server_restart()
{

    load_game_runtime || return 1


    echo
    echo "Reiniciando servidor:"
    echo "Game: $(runtime_game)"
    echo "Instance: $(runtime_instance)"
    echo


    if declare -F runtime_restart >/dev/null
    then

        runtime_restart
        publish_server_state

    else

        echo "runtime_restart não implementado:"
        echo "$(runtime_game)"

        return 1

    fi

}


# =============================================================
# Export
# =============================================================

export -f server_restart


# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    server_restart

fi