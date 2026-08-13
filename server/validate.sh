#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Server Validate Module
#
# Responsável:
# Orquestrar validação da instância atual
#
# Arquitetura:
#
# Core não conhece jogos.
# Cada jogo fornece seu Game Adapter.
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# =============================================================
# Context
# =============================================================

source "${DSM_ROOT}/core/runtime/context.sh"


# =============================================================
# Carregar adapter do jogo
# =============================================================

load_game_validator()
{

    local GAME

    GAME="$(runtime_game | tr '[:upper:]' '[:lower:]')"


    local VALIDATOR

    VALIDATOR="${DSM_ROOT}/games/${GAME}/validate.sh"


    if [[ ! -f "${VALIDATOR}" ]]
    then
        echo "Validator não encontrado:"
        echo "${VALIDATOR}"

        return 1
    fi


    source "${VALIDATOR}"

}


# =============================================================
# Validate
# =============================================================

server_validate()
{

    load_game_validator || return 1


    echo
    echo "Validando:"
    echo "Game: $(runtime_game)"
    echo "Instance: $(runtime_instance)"
    echo


    if declare -F game_validate >/dev/null
    then

        game_validate

    else

        echo "game_validate não implementado:"
        echo "$(runtime_game)"

        return 1

    fi

}


# =============================================================
# Export
# =============================================================

export -f server_validate


# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    server_validate
fi