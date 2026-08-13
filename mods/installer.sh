#!/bin/bash
# =============================================================
# mods/installer.sh - MÓDULO 03 (MODS)
#
# Orquestrador de instalação de Mods DayZ
# DayZ Mods installation orchestrator
#
# Responsável por: | Responsible for:
# - preparar instalação | preparing installation
# - controlar pipeline | controlling pipeline
# - chamar download | calling download
# - chamar sincronização | calling synchronization
# - atualizar estado | updating state
#
# NÃO FAZ: | DOES NOT DO:
# - rsync
# - SteamCMD direto | direct SteamCMD
# - cópia de arquivos | file copying
# - gerenciamento de keys | keys management
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

# shellcheck source=/dev/null
source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Diretórios | Directories
# =============================================================
MODS_DIR="${SERVERFILES_PATH}/mods"
KEYS_DIR="${SERVERFILES_PATH}/keys"

# =============================================================
# Preparação | Preparation
# =============================================================
mods_prepare()
{
    mkdir -p \
        "${MODS_DIR}" \
        "${KEYS_DIR}"

    log_ok \
    "Diretórios de Mods preparados."
    log_ok \
    "Mods directories prepared."
}

# =============================================================
# Instalar um mod | Install a mod
#
# Uso: | Usage:
# installer_install ID @MOD
# =============================================================
installer_install()
{
     local workshop_id="$1"
        local folder="$2"

        if [ -z "${workshop_id}" ] ||
           [ -z "${folder}" ]
        then
            log_error \
            "Uso | Usage: installer_install ID @MOD"
            return 1
        fi

        log_info \
        "Instalando | Installing ${folder}"

        # Download Workshop
        if ! steamcmd_download_item "${workshop_id}"
        then
            log_error \
            "Falha no download | Download failed: ${folder}"
            return 1
        fi

        # Sincronização Workshop -> mods | Workshop -> mods synchronization
        if ! mods_sync \
            "${workshop_id}" \
            "${folder}"
        then
            log_error \
            "Falha na sincronização | Synchronization failed: ${folder}"
            return 1
        fi

        # Atualizar estado | Update state
        local info
        local timestamp
        info="$(steamcmd_workshop_info "${workshop_id}")"
        timestamp="$(steamcmd_workshop_updated "${info}")"

        state_set \
            "${workshop_id}" \
            "${timestamp}" \
            "${folder}"

        log_ok \
        "${folder} instalado | installed."
        echo "${folder}"
}

# =============================================================
# Instalação completa | Full installation
# =============================================================
mods_install_all()
{
    mods_prepare || return 1
    mods_detect_or_load_workshop_ids || return 1

    local item
    for item in "${MOD_LIST[@]}"
    do
        local id
        local folder
        id="${item%%:*}"
        folder="${item##*:}"
        id="$(echo "${id}" | xargs)"
        folder="$(echo "${folder}" | xargs)"
        [ -z "${id}" ] && continue

        if [ -d "${MODS_DIR}/${folder}" ]
        then
            log_info \
            "${folder} já instalado | already installed."
            continue
        fi

        installer_install \
            "${id}" \
            "${folder}" || return 1
    done

    keys_sync
    log_ok \
    "Instalação de Mods concluída."
    log_ok \
    "Mods installation completed."
}

# =============================================================
# Encontrar mod existente | Find existing mod
#
# Usado pelo updater | Used by the updater
# =============================================================
installer_find_existing()
{
    local id="$1"
    for mod in "${MODS_DIR}"/*
    do
        [ -d "${mod}" ] || continue
        if grep -R \
            -q \
            "publishedid *= *${id}" \
            "${mod}" \
            2>/dev/null
        then
            basename "${mod}"
            return 0
        fi
    done
    return 1
}

# =============================================================
# Listagem | Listing
# =============================================================
mods_list()
{
    find "${MODS_DIR}" \
        -maxdepth 1 \
        -type d \
        -name "@*" \
        -printf "%f\n"
}

# =============================================================
# Dispatcher
# =============================================================
installer_command()
{
case "$1" in
    install)
        mods_install_all
    ;;
    prepare)
        mods_prepare
    ;;
    list)
        mods_list
    ;;
    *)
        echo
        echo "Uso | Usage:"
        echo
        echo " installer.sh install"
        echo " installer.sh prepare"
        echo " installer.sh list"
        return 1
    ;;
esac
}

# =============================================================
# Execução direta | Direct execution
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    installer_command "$@"
fi
