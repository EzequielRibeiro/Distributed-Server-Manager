#!/usr/bin/env bash

# =============================================================
# Capivara DSM - Example Custom Provider
# Demonstrates Custom Provider Contract v1.
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
source "${DSM_ROOT}/installer/custom_provider_contract.sh"

DSM_PROVIDER_API_VERSION="1"
DSM_PROVIDER_KIND="custom"
DSM_PROVIDER_NAME="example-custom"

example_custom_log()
{
    echo "[DSM][CUSTOM][example-custom] $*"
}

provider_ensure()
{
    command -v cp >/dev/null 2>&1 || return 1
    command -v sha256sum >/dev/null 2>&1 || return 1
    return 0
}

provider_install()
{
    local SOURCE="${1:-}"
    local INSTALL_PATH="${2:-}"
    local AUTH="${3:-}"
    local EXPECTED_EXECUTABLE="${4:-${DSM_EXPECTED_EXECUTABLE:-}}"
    local NAME DESTINATION ACTUAL EXPECTED VERSION

    [[ -f "${SOURCE}" ]] || {
        example_custom_log "Origem inválida: ${SOURCE}"
        return 1
    }

    [[ -n "${INSTALL_PATH}" && "${INSTALL_PATH}" != "/" ]] || return 1

    NAME="${DSM_CUSTOM_FILENAME:-$(basename "${SOURCE}")}"
    [[ "${NAME}" != */* && "${NAME}" != "." && "${NAME}" != ".." ]] || return 1

    DESTINATION="${INSTALL_PATH}/${NAME}"
    EXPECTED="${DSM_CUSTOM_SHA256:-}"
    VERSION="${DSM_CUSTOM_VERSION:-current}"

    mkdir -p "${INSTALL_PATH}"
    custom_provider_progress "copying" 35 "Custom provider: copiando pacote"
    cp -f -- "${SOURCE}" "${DESTINATION}" || return 1

    if [[ "${DSM_CUSTOM_EXECUTABLE:-0}" == "1" || \
          ( -n "${EXPECTED_EXECUTABLE}" && "${NAME}" == "${EXPECTED_EXECUTABLE}" ) ]]
    then
        custom_provider_progress "installing" 55 "Custom provider: aplicando permissão de execução"
        chmod +x "${DESTINATION}" || return 1
    fi

    ACTUAL="$(sha256sum "${DESTINATION}" | awk '{print $1}')" || return 1

    if [[ -n "${EXPECTED}" && "${ACTUAL,,}" != "${EXPECTED,,}" ]]
    then
        example_custom_log "SHA256 inválido."
        rm -f -- "${DESTINATION}"
        return 1
    fi

    custom_provider_progress "validating" 68 "Custom provider: checksum validado"

    mkdir -p "${INSTALL_PATH}/.dsm"
    {
        printf 'PROVIDER=%q\n' "example-custom"
        printf 'SOURCE=%q\n' "${SOURCE}"
        printf 'FILENAME=%q\n' "${NAME}"
        printf 'SHA256=%q\n' "${ACTUAL}"
        printf 'VERSION=%q\n' "${VERSION}"
    } > "${INSTALL_PATH}/.dsm/custom-provider.conf"

    custom_provider_progress "copied" 75 "Custom provider: pacote preparado"
    example_custom_log "Instalação concluída no staging."
    return 0
}

provider_update()
{
    provider_install "$@"
}

provider_verify()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local EXECUTABLE="${3:-}"
    local META FILE ACTUAL

    META="${INSTALL_PATH}/.dsm/custom-provider.conf"
    [[ -f "${META}" ]] || return 1

    # shellcheck source=/dev/null
    source "${META}"

    FILE="${INSTALL_PATH}/${FILENAME:-}"
    [[ -f "${FILE}" ]] || return 1

    if [[ -n "${SHA256:-}" ]]
    then
        ACTUAL="$(sha256sum "${FILE}" | awk '{print $1}')" || return 1
        [[ "${ACTUAL,,}" == "${SHA256,,}" ]] || return 1
    fi

    if [[ -n "${EXECUTABLE}" ]]
    then
        [[ -x "${INSTALL_PATH}/${EXECUTABLE}" ]] || return 1
    fi

    return 0
}

provider_info()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local META="${INSTALL_PATH}/.dsm/custom-provider.conf"

    if [[ ! -f "${META}" ]]
    then
        echo "provider=example-custom"
        echo "source=${PACKAGE_ID}"
        echo "version=unknown"
        return 1
    fi

    # shellcheck source=/dev/null
    source "${META}"
    echo "provider=example-custom"
    echo "source=${SOURCE:-${PACKAGE_ID}}"
    echo "file=${FILENAME:-unknown}"
    echo "version=${VERSION:-current}"
}

provider_version()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local META="${INSTALL_PATH}/.dsm/custom-provider.conf"

    if [[ ! -f "${META}" ]]
    then
        echo "unknown"
        return 1
    fi

    # shellcheck source=/dev/null
    source "${META}"
    echo "${VERSION:-current}"
}

export -f provider_ensure provider_install provider_update provider_verify provider_info provider_version
