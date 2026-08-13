#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Server Status Module
#
# Responsável:
#
# Consultar estado da instância atual
#
# Não conhece jogos.
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
# Carregar Runtime do jogo
# =============================================================

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


# =============================================================
# Status
# =============================================================

server_status()
{

    load_game_runtime || return 1


    if declare -F runtime_status >/dev/null
    then

        runtime_status

    else

        echo "runtime_status não implementado"
        return 1

    fi

}


# =============================================================
# JSON
# =============================================================

server_status_json()
{

    load_game_runtime || return 1


    local STATUS

    STATUS="$(runtime_status)"


    local INFO

    if declare -F runtime_info >/dev/null
    then
        INFO="$(runtime_info)"
    else
        INFO="{}"
    fi


    cat <<EOF
{
 "identity": {
   "host": "$(runtime_host)",
   "node": "$(runtime_node)",
   "game": "$(runtime_game)",
   "instance": "$(runtime_instance)"
 },
 "status": {
   "state": "${STATUS}",
   "info": ${INFO}
 }
}
EOF

}


# =============================================================
# Export
# =============================================================

export -f server_status
export -f server_status_json


# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    server_status

fi