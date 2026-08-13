#!/bin/bash

# =============================================================
# Capivara DSM
#
# Universal Game Loader
#
# Responsável por carregar adaptadores dos jogos
#
# Carrega:
#   - game.conf
#   - process.sh
#   - runtime.sh
#
# Não inicia o jogo.
# Apenas prepara o ambiente.
#
# =============================================================


game_loader()
{

    local GAME="${1:-${DSM_GAME:-}}"


    if [[ -z "${GAME}" ]]
    then
        echo "Jogo não informado."
        return 1
    fi


    GAME_ID=$(echo "${GAME}" | tr '[:upper:]' '[:lower:]')


    GAME_DIR="${DSM_ROOT}/games/${GAME_ID}"


    if [[ ! -d "${GAME_DIR}" ]]
    then
        echo "Jogo não encontrado:"
        echo "${GAME_DIR}"
        return 1
    fi


    echo "Carregando jogo:"
    echo "${GAME_ID}"


    #
    # Identidade do jogo
    #

    export GAME_ID
    export DSM_GAME="${GAME_ID}"

    export DSM_GAME_DIR="${GAME_DIR}"


    #
    # Configuração do jogo
    #

    if [[ -f "${GAME_DIR}/game.conf" ]]
    then

        source "${GAME_DIR}/game.conf"

    fi


    #
    # Configuração do processo
    #

    if [[ -f "${GAME_DIR}/process.sh" ]]
    then

        source "${GAME_DIR}/process.sh"

    fi


    #
    # Runtime específico do jogo
    #

    if [[ -f "${GAME_DIR}/runtime.sh" ]]
    then

        source "${GAME_DIR}/runtime.sh"

    else

        echo "Runtime não encontrado:"
        echo "${GAME_DIR}/runtime.sh"

        return 1

    fi


    return 0

}


export -f game_loader