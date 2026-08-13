#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Installation Manager - Rollback
#
# Responsável:
# - restaurar instalação anterior
# - preservar instalação com problema para diagnóstico
# =============================================================


install_rollback()
{
    local INSTALL_PATH="$1"

    local OLD_PATH="${INSTALL_PATH}.old"
    local FAILED_PATH="${INSTALL_PATH}.failed"

    echo
    echo "============================================"
    echo " Capivara - Installation Rollback"
    echo "============================================"
    echo

    if [[ ! -d "${OLD_PATH}" ]]
    then
        echo "[ERRO] Nenhuma instalação anterior disponível:"
        echo "${OLD_PATH}"

        return 1
    fi

    # ---------------------------------------------------------
    # Preservar instalação atual
    # ---------------------------------------------------------

    if [[ -d "${INSTALL_PATH}" ]]
    then
        rm -rf "${FAILED_PATH}"

        echo "Preservando instalação com problema:"
        echo "${FAILED_PATH}"

        mv "${INSTALL_PATH}" "${FAILED_PATH}"
    fi

    # ---------------------------------------------------------
    # Restaurar anterior
    # ---------------------------------------------------------

    echo
    echo "Restaurando:"
    echo "${OLD_PATH}"
    echo

    mv "${OLD_PATH}" "${INSTALL_PATH}"

    if [[ ! -d "${INSTALL_PATH}" ]]
    then
        echo "[ERRO] Rollback falhou."
        return 1
    fi

    echo "Rollback concluído."

    return 0
}


install_rollback_available()
{
    local INSTALL_PATH="$1"

    [[ -d "${INSTALL_PATH}.old" ]]
}


export -f install_rollback
export -f install_rollback_available