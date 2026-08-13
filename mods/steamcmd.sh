#!/bin/bash
# =============================================================
# mods/steamcmd.sh - MÓDULO 03 (MODS)
# Wrapper SteamCMD + Steam Workshop API
# Responsável por:
# - localizar SteamCMD
# - consultar Workshop
# - baixar mods
# - validar downloads
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap DSM
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Dependências
# =============================================================
source "${DSM_ROOT}/core/lock.sh"
if [ -f "${DSM_ROOT}/monitor/events.sh" ]
then
    source "${DSM_ROOT}/monitor/events.sh"
fi

# =============================================================
# Configuração DSM
# =============================================================
DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"
if [ -f "${DSM_CONFIG}" ]
then
    source "${DSM_CONFIG}"
fi

# =============================================================
# Defaults
# =============================================================
STEAMCMD_DIR="${STEAMCMD_DIR:-${DSM_HOME}/steamcmd}"
SERVERFILES_PATH="${SERVERFILES_PATH:-${DSM_HOME}/steamcmd/serverfiles}"
APPID_WORKSHOP="${APPID_WORKSHOP:-221100}"

# =============================================================
# Caminho Workshop
# =============================================================
steamcmd_item_path()
{
    local workshop_id="$1"
    echo \
    "${SERVERFILES_PATH}/steamapps/workshop/content/${APPID_WORKSHOP}/${workshop_id}"
}

# =============================================================
# SteamCMD binário
# =============================================================
steamcmd_bin()
{
    echo "${STEAMCMD_DIR}/steamcmd.sh"
}

steamcmd_installed()
{
    local bin
    bin="$(steamcmd_bin)"
    [ -x "${bin}" ]
}

# =============================================================
# Validação SteamCMD
# =============================================================
steamcmd_check()
{
    if ! steamcmd_installed
    then
        log_error \
        "SteamCMD não encontrado: $(steamcmd_bin)"
        return 1
    fi
    return 0
}

# =============================================================
# Steam Workshop API
# ISteamRemoteStorage/GetPublishedFileDetails
# =============================================================
steamcmd_workshop_info()
{
    local id="$1"
    if ! [[ "${id}" =~ ^[0-9]+$ ]]
    then
        echo "{}"
        return 1
    fi

    curl \
    --silent \
    --show-error \
    --fail \
    --connect-timeout 10 \
    --max-time 30 \
    -X POST \
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/" \
    --data-urlencode "itemcount=1" \
    --data-urlencode "publishedfileids[0]=${id}"
}

steamcmd_workshop_title()
{
    local json="$1"
    echo "${json}" | jq -r \
    '.response.publishedfiledetails[0].title // "desconhecido"'
}

steamcmd_workshop_updated()
{
    local json="$1"
    echo "${json}" | jq -r \
    '.response.publishedfiledetails[0].time_updated // 0'
}

steamcmd_workshop_size()
{
    local json="$1"
    echo "${json}" | jq -r \
    '.response.publishedfiledetails[0].file_size // 0'
}

# =============================================================
# Download Workshop Item
# APPID DayZ:
# 221100
# =============================================================
steamcmd_download_item()
{
    local id="$1"
    if ! [[ "${id}" =~ ^[0-9]+$ ]]
    then
        log_error \
        "Workshop ID inválido: ${id}"
        return 1
    fi

    steamcmd_check || return 1

    if ! lock_acquire "steamcmd-${id}"
    then
        log_warn \
        "Download já em execução para Workshop ${id}"
        return 1
    fi

    mkdir -p \
    "${DSM_ROOT}/logs"

    local log_file
    log_file="${DSM_ROOT}/logs/steamcmd_${id}.log"

    log_info \
    "Baixando Workshop ID ${id}"

    "$(steamcmd_bin)" \
        +force_install_dir "${SERVERFILES_PATH}" \
        +login anonymous \
        +workshop_download_item "${APPID_WORKSHOP}" "${id}" validate \
        +quit \
        > "${log_file}" 2>&1

    local rc=$?
    if [ "${rc}" -ne 0 ]
    then
        log_error \
        "SteamCMD falhou no Workshop ${id}"
        lock_release "steamcmd-${id}"
        return 1
    fi

    if ! steamcmd_item_exists "${id}"
    then
        log_error \
        "Download finalizado mas conteúdo não encontrado: ${id}"
        lock_release "steamcmd-${id}"
        return 1
    fi

    log_ok \
    "Workshop ${id} baixado com sucesso"

    events_emit \
    "mods.download" \
    "Workshop ${id} baixado"

    lock_release "steamcmd-${id}"
    return 0
}

# =============================================================
# Verifica conteúdo baixado
# =============================================================
steamcmd_item_exists()
{
    local id="$1"
    local path
    path="$(steamcmd_item_path "${id}")"

    [ -d "${path}" ] && \
    [ -n "$(find "${path}" -mindepth 1 -print -quit 2>/dev/null)" ]
}

# =============================================================
# Exportação
# =============================================================
export -f steamcmd_item_path
export -f steamcmd_bin
export -f steamcmd_installed
export -f steamcmd_check
export -f steamcmd_workshop_info
export -f steamcmd_workshop_title
export -f steamcmd_workshop_updated
export -f steamcmd_workshop_size
export -f steamcmd_download_item
export -f steamcmd_item_exists
