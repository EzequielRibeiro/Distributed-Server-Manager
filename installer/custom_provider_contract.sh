#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Custom Provider Contract v1
# =============================================================
# Custom providers are trusted administrator extensions executed
# inside the Agent process context. They MUST implement:
#   provider_ensure
#   provider_install
#   provider_update
#   provider_verify
#   provider_info
#   provider_version
#
# Required metadata:
#   DSM_PROVIDER_API_VERSION="1"
#   DSM_PROVIDER_KIND="custom"
#   DSM_PROVIDER_NAME="provider-name"
#
# provider_install arguments:
#   $1 PACKAGE_ID
#   $2 INSTALL_PATH (staging)
#   $3 AUTH/context
# Optional execution context is also exposed by the Atomic Engine:
#   DSM_EXPECTED_EXECUTABLE
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/installer/provider_progress.sh"

CUSTOM_PROVIDER_API_VERSION="1"

custom_provider_contract_error()
{
    echo "[DSM][CUSTOM-PROVIDER][ERRO] $*" >&2
}

custom_provider_contract_validate_metadata()
{
    local EXPECTED_NAME="${1:-}"

    if [[ "${DSM_PROVIDER_API_VERSION:-}" != "${CUSTOM_PROVIDER_API_VERSION}" ]]
    then
        custom_provider_contract_error \
            "API incompatível: esperado=${CUSTOM_PROVIDER_API_VERSION} recebido=${DSM_PROVIDER_API_VERSION:-none}"
        return 1
    fi

    if [[ "${DSM_PROVIDER_KIND:-}" != "custom" ]]
    then
        custom_provider_contract_error "DSM_PROVIDER_KIND deve ser 'custom'."
        return 1
    fi

    if [[ -z "${DSM_PROVIDER_NAME:-}" ]]
    then
        custom_provider_contract_error "DSM_PROVIDER_NAME não definido."
        return 1
    fi

    if [[ -n "${EXPECTED_NAME}" && "${DSM_PROVIDER_NAME}" != "${EXPECTED_NAME}" ]]
    then
        custom_provider_contract_error \
            "Nome do provider não corresponde ao arquivo: ${DSM_PROVIDER_NAME} != ${EXPECTED_NAME}"
        return 1
    fi

    return 0
}

custom_provider_contract_validate_functions()
{
    local FUNCTION

    for FUNCTION in \
        provider_ensure \
        provider_install \
        provider_update \
        provider_verify \
        provider_info \
        provider_version
    do
        if ! declare -F "${FUNCTION}" >/dev/null 2>&1
        then
            custom_provider_contract_error "Função obrigatória ausente: ${FUNCTION}()"
            return 1
        fi
    done

    return 0
}

custom_provider_contract_validate()
{
    local EXPECTED_NAME="${1:-}"
    custom_provider_contract_validate_metadata "${EXPECTED_NAME}" || return 1
    custom_provider_contract_validate_functions || return 1
    return 0
}

custom_provider_progress()
{
    local STAGE="${1:-processing}"
    local PROGRESS="${2:-25}"
    local MESSAGE="${3:-Custom provider}"

    provider_progress_publish "${STAGE}" "${PROGRESS}" "${MESSAGE}"
}

export -f custom_provider_contract_error
export -f custom_provider_contract_validate_metadata
export -f custom_provider_contract_validate_functions
export -f custom_provider_contract_validate
export -f custom_provider_progress
