#!/usr/bin/env bash

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/core/runtime/context.sh"

# =============================================================
# Publisher
# =============================================================

source "${DSM_ROOT}/core/runtime/publisher.sh"

load_game_runtime()
{
    local GAME

    GAME="$(runtime_game | tr '[:upper:]' '[:lower:]')"

    local RUNTIME
    RUNTIME="${DSM_ROOT}/games/${GAME}/runtime.sh"

    if [[ ! -f "${RUNTIME}" ]]
    then
        echo "Runtime não encontrado:"
        echo "${RUNTIME}"
        return 1
    fi

    source "${RUNTIME}"
}


server_start()
{
    load_game_runtime || return 1

    echo
    echo "Iniciando:"
    echo "Game: $(runtime_game)"
    echo "Instance: $(runtime_instance)"
    echo


    if ! declare -F runtime_start >/dev/null
    then
        echo "runtime_start não implementado para:"
        echo "$(runtime_game)"
        return 1
    fi


    runtime_start
    publish_server_state

}


export -f server_start


if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    server_start
fi