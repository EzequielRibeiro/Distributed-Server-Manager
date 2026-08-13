#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# DayZ Validate Adapter
#
# Responsável por:
#
# - validar configuração da instância
# - validar instalação compartilhada do DayZ
# - validar executável
# - validar launcher da instância
#
# Arquitetura:
#
#   Game Installation:
#     /opt/dsm/game-data/dayz/serverfiles
#
#   Instance:
#     /opt/dsm/instances/<node>/dayz/<instance>
#
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# =============================================================
# Runtime Context
# =============================================================

source "${DSM_ROOT}/core/runtime/context.sh"

# =============================================================
# Validação DayZ
# =============================================================

game_validate()
{
    local INSTANCE
    local CONF
    local EXEC

    INSTANCE="$(get_instance_path)"
    CONF="${INSTANCE}/instance.conf"

    echo
    echo "Validando DayZ:"
    echo "================"
    echo

    # =========================================================
    # Instância
    # =========================================================

    if [[ ! -d "${INSTANCE}" ]]
    then
        echo "[ERRO] Instância não encontrada:"
        echo "${INSTANCE}"

        return 1
    fi

    echo "[OK] Instância:"
    echo "${INSTANCE}"

    # =========================================================
    # instance.conf
    # =========================================================

    if [[ ! -f "${CONF}" ]]
    then
        echo "[ERRO] instance.conf ausente:"
        echo "${CONF}"

        return 1
    fi

    echo "[OK] instance.conf"

    # shellcheck source=/dev/null
    source "${CONF}"

    # =========================================================
    # GAME
    # =========================================================

    if [[ -z "${GAME:-}" ]]
    then
        echo "[ERRO] GAME não definido no instance.conf"

        return 1
    fi

    if [[ "${GAME,,}" != "dayz" ]]
    then
        echo "[ERRO] Instância não pertence ao DayZ:"
        echo "${GAME}"

        return 1
    fi

    echo "[OK] Game: ${GAME}"

    # =========================================================
    # Instance ID
    # =========================================================

    if [[ -z "${INSTANCE_ID:-}" ]]
    then
        echo "[ERRO] INSTANCE_ID não definido"

        return 1
    fi

    echo "[OK] Instance ID: ${INSTANCE_ID}"

    # =========================================================
    # Game Installation
    # =========================================================

    if [[ -z "${GAME_INSTALL:-}" ]]
    then
        echo "[ERRO] GAME_INSTALL não definido no instance.conf"

        return 1
    fi

    if [[ ! -d "${GAME_INSTALL}" ]]
    then
        echo "[ERRO] Instalação do DayZ não encontrada:"
        echo "${GAME_INSTALL}"

        return 1
    fi

    echo "[OK] Game Installation:"
    echo "${GAME_INSTALL}"

    # =========================================================
    # Executável
    # =========================================================

    if [[ -z "${EXECUTABLE:-}" ]]
    then
        echo "[ERRO] EXECUTABLE não definido"

        return 1
    fi

    EXEC="${GAME_INSTALL}/${EXECUTABLE}"

    if [[ ! -f "${EXEC}" ]]
    then
        echo "[ERRO] Executável não encontrado:"
        echo "${EXEC}"

        return 1
    fi

    if [[ ! -x "${EXEC}" ]]
    then
        echo "[ERRO] Executável sem permissão de execução:"
        echo "${EXEC}"

        return 1
    fi

    echo "[OK] Executável:"
    echo "${EXEC}"

    # =========================================================
    # Arquitetura ELF
    # =========================================================

    if ! file "${EXEC}" | grep -q "ELF 64-bit"
    then
        echo "[ERRO] Executável inválido ou arquitetura incompatível:"
        file "${EXEC}"

        return 1
    fi

    echo "[OK] Executável Linux 64-bit"

    # =========================================================
    # Launcher
    # =========================================================

    if [[ ! -f "${INSTANCE}/launcher.sh" ]]
    then
        echo "[ERRO] launcher.sh ausente:"
        echo "${INSTANCE}/launcher.sh"

        return 1
    fi

    if [[ ! -x "${INSTANCE}/launcher.sh" ]]
    then
        echo "[ERRO] launcher.sh sem permissão de execução:"
        echo "${INSTANCE}/launcher.sh"

        return 1
    fi

    echo "[OK] launcher.sh"

    # =========================================================
    # serverDZ.cfg
    # =========================================================

    local SERVER_CONFIG

    SERVER_CONFIG="${INSTANCE}/serverDZ.cfg"

    if [[ ! -f "${SERVER_CONFIG}" ]]
    then
        echo "[ERRO] serverDZ.cfg não encontrado:"
        echo "${SERVER_CONFIG}"

        return 1
    fi

    echo "[OK] serverDZ.cfg"

    # =========================================================
    # Mission
    # =========================================================

    local MISSION

    MISSION="$(
        grep -E '^[[:space:]]*template[[:space:]]*=' \
            "${SERVER_CONFIG}" \
            | head -n1 \
            | sed -E 's/.*template[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/'
    )"

    if [[ -z "${MISSION}" ]]
    then
        echo "[ERRO] Missão não encontrada no serverDZ.cfg"

        return 1
    fi

    echo "[OK] Mission:"
    echo "${MISSION}"

    if [[ ! -d "${GAME_INSTALL}/mpmissions/${MISSION}" ]]
    then
        echo "[ERRO] Diretório da missão não encontrado:"
        echo "${GAME_INSTALL}/mpmissions/${MISSION}"

        return 1
    fi

    echo "[OK] Mission instalada"

    # =========================================================
    # Profiles
    # =========================================================

    if [[ ! -d "${INSTANCE}/profiles" ]]
    then
        echo "[ERRO] Diretório profiles não encontrado:"
        echo "${INSTANCE}/profiles"

        return 1
    fi

    if [[ ! -w "${INSTANCE}/profiles" ]]
    then
        echo "[ERRO] Diretório profiles sem permissão de escrita:"
        echo "${INSTANCE}/profiles"

        return 1
    fi

    echo "[OK] Profiles"

    # =========================================================
    # Storage
    # =========================================================

    if [[ ! -d "${INSTANCE}/storage" ]]
    then
        echo "[ERRO] Diretório storage não encontrado:"
        echo "${INSTANCE}/storage"

        return 1
    fi

    if [[ ! -w "${INSTANCE}/storage" ]]
    then
        echo "[ERRO] Diretório storage sem permissão de escrita:"
        echo "${INSTANCE}/storage"

        return 1
    fi

    echo "[OK] Storage"

    # =========================================================
    # Final
    # =========================================================

    echo
    echo "============================================"
    echo " DayZ - Validação concluída"
    echo "============================================"
    echo
    echo "Game        : ${GAME}"
    echo "Instance    : ${INSTANCE_ID}"
    echo "Installation: ${GAME_INSTALL}"
    echo "Executable  : ${EXEC}"
    echo "Mission     : ${MISSION}"
    echo
    echo "Status      : OK"
    echo

    return 0
}

# =============================================================
# Export API
# =============================================================

export -f game_validate

# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    game_validate
fi