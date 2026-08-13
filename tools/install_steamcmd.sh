#!/usr/bin/env bash

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

STEAMCMD_ROOT="${DSM_ROOT}/tools/steamcmd"
STEAMCMD_URL="https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_ARCHIVE="${STEAMCMD_ROOT}/steamcmd_linux.tar.gz"
STEAMCMD_BIN="${STEAMCMD_ROOT}/steamcmd.sh"

steamcmd_install_log()
{
    echo "[DSM][STEAMCMD] $*"
}

steamcmd_install_error()
{
    echo "[DSM][STEAMCMD][ERROR] $*" >&2
}

steamcmd_install_requirements()
{
    local COMMAND

    for COMMAND in curl tar
    do
        if ! command -v "${COMMAND}" >/dev/null 2>&1
        then
            steamcmd_install_error "Dependência não encontrada: ${COMMAND}"
            return 1
        fi
    done

    return 0
}

steamcmd_install_permissions()
{
    local BIN

    if [[ -f "${STEAMCMD_BIN}" ]]
    then
        chmod +x "${STEAMCMD_BIN}"
    fi

    for BIN in \
        "${STEAMCMD_ROOT}/linux32/steamcmd" \
        "${STEAMCMD_ROOT}/linux64/steamcmd"
    do
        if [[ -f "${BIN}" ]]
        then
            chmod +x "${BIN}"
        fi
    done

    return 0
}

steamcmd_install_validate()
{
    if [[ ! -x "${STEAMCMD_BIN}" ]]
    then
        steamcmd_install_error "Launcher SteamCMD ausente ou não executável:"
        steamcmd_install_error "${STEAMCMD_BIN}"
        return 1
    fi

    if [[ -f "${STEAMCMD_ROOT}/linux32/steamcmd" ]] &&
       [[ ! -x "${STEAMCMD_ROOT}/linux32/steamcmd" ]]
    then
        steamcmd_install_error "Binário linux32 do SteamCMD não é executável."
        return 1
    fi

    if [[ -f "${STEAMCMD_ROOT}/linux64/steamcmd" ]] &&
       [[ ! -x "${STEAMCMD_ROOT}/linux64/steamcmd" ]]
    then
        steamcmd_install_error "Binário linux64 do SteamCMD não é executável."
        return 1
    fi

    return 0
}

steamcmd_install()
{
    steamcmd_install_requirements || return 1

    steamcmd_install_log "Preparando diretório:"
    steamcmd_install_log "${STEAMCMD_ROOT}"

    mkdir -p "${STEAMCMD_ROOT}"

    steamcmd_install_log "Baixando SteamCMD..."

    if ! curl \
        --fail \
        --location \
        --silent \
        --show-error \
        --output "${STEAMCMD_ARCHIVE}" \
        "${STEAMCMD_URL}"
    then
        steamcmd_install_error "Falha ao baixar SteamCMD."
        rm -f -- "${STEAMCMD_ARCHIVE}"
        return 1
    fi

    steamcmd_install_log "Extraindo SteamCMD..."

    if ! tar -xzf "${STEAMCMD_ARCHIVE}" -C "${STEAMCMD_ROOT}"
    then
        steamcmd_install_error "Falha ao extrair SteamCMD."
        rm -f -- "${STEAMCMD_ARCHIVE}"
        return 1
    fi

    rm -f -- "${STEAMCMD_ARCHIVE}"

    steamcmd_install_permissions || return 1

    steamcmd_install_log "Executando bootstrap do SteamCMD..."

    if ! "${STEAMCMD_BIN}" +quit
    then
        steamcmd_install_error "Bootstrap do SteamCMD falhou."
        return 1
    fi

    steamcmd_install_permissions || return 1
    steamcmd_install_validate || return 1

    steamcmd_install_log "SteamCMD instalado com sucesso."
    return 0
}

steamcmd_install "$@"
