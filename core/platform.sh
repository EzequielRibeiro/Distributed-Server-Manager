#!/usr/bin/env bash
# =============================================================
# DSM Core - Universal Platform
#
# Responsável por carregar o jogo ativo.
# =============================================================

set -Eeuo pipefail

DSM_ROOT="/opt/dsm"

CURRENT_GAME="${DSM_GAME:-dayz}"

GAME_DIR="${DSM_ROOT}/games/${CURRENT_GAME}"

detect_game() {
    echo "${CURRENT_GAME}"
}

game_directory() {
    echo "${GAME_DIR}"
}

game_exists() {
    [[ -d "${GAME_DIR}" ]]
}

load_game() {

    if ! game_exists; then
        echo "Game '${CURRENT_GAME}' not found."
        return 1
    fi

    source "${GAME_DIR}/game.conf"
    source "${GAME_DIR}/runtime.sh"
}

platform_name() {
    echo "DSM Universal Platform"
}

platform_version() {
    echo "2.1.0"
}