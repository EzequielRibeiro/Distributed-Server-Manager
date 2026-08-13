#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# DayZ Installation Adapter
#
# Responsável:
#
# - carregar configuração DayZ
# - delegar instalação ao Installation Manager
#
# NÃO implementa:
#
# - SteamCMD
# - atomic swap
# - rollback
# - integrity engine
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

GAME_ID="dayz"

# =============================================================
# Installation Manager
# =============================================================

source "${DSM_ROOT}/installer/manager.sh"

# =============================================================
# Install
# =============================================================

dayz_install()
{
    install_manager_install "${GAME_ID}"
}

# =============================================================
# Update
# =============================================================

dayz_update()
{
    install_manager_update "${GAME_ID}"
}

# =============================================================
# Validate
# =============================================================

dayz_install_validate()
{
    install_manager_validate "${GAME_ID}"
}

# =============================================================
# Rollback
# =============================================================

dayz_install_rollback()
{
    install_manager_rollback "${GAME_ID}"
}

# =============================================================
# Info
# =============================================================

dayz_install_info()
{
    install_manager_info "${GAME_ID}"
}

# =============================================================
# Export API
# =============================================================

export -f dayz_install
export -f dayz_update
export -f dayz_install_validate
export -f dayz_install_rollback
export -f dayz_install_info

# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    dayz_install
fi