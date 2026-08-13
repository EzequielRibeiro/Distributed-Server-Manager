#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Universal Integrity Engine
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

integrity_log(){ echo "[DSM][INTEGRITY] $*"; }
integrity_error(){ echo "[DSM][INTEGRITY][ERRO] $*" >&2; }

integrity_check_directory()
{
    local PATH_TO_CHECK="${1:-}"
    [[ -n "${PATH_TO_CHECK}" ]] && [[ -d "${PATH_TO_CHECK}" ]]
}

integrity_check_file()
{
    local PATH_TO_CHECK="${1:-}"
    [[ -n "${PATH_TO_CHECK}" ]] && [[ -f "${PATH_TO_CHECK}" ]] && [[ -r "${PATH_TO_CHECK}" ]]
}

integrity_check_executable()
{
    local PATH_TO_CHECK="${1:-}"
    [[ -n "${PATH_TO_CHECK}" ]] && [[ -f "${PATH_TO_CHECK}" ]] && [[ -x "${PATH_TO_CHECK}" ]]
}

integrity_check_artifact()
{
    local PATH_TO_CHECK="${1:-}"
    local MODE="${2:-executable}"

    case "${MODE}" in
        executable|native|directory) integrity_check_executable "${PATH_TO_CHECK}" ;;
        file|java|jar) integrity_check_file "${PATH_TO_CHECK}" ;;
        *) integrity_error "Modo de integridade desconhecido: ${MODE}"; return 1 ;;
    esac
}

integrity_provider_verify()
{
    local PACKAGE_ID="$1"
    local INSTALL_PATH="$2"
    local EXECUTABLE="$3"

    if ! declare -F provider_verify >/dev/null
    then
        integrity_log "Provider não possui verificação adicional."
        return 0
    fi

    provider_verify "${PACKAGE_ID}" "${INSTALL_PATH}" "${EXECUTABLE}"
}

integrity_validate()
{
    local INSTALL_PATH="${1:-}"
    local PACKAGE_ID="${2:-}"
    local EXECUTABLE="${3:-}"
    local ARTIFACT_MODE="${4:-${DSM_INTEGRITY_ARTIFACT_MODE:-executable}}"
    local EXEC_PATH STATUS="healthy" LABEL="Executável"

    echo
    echo "============================================"
    echo " Capivara - Integrity Check"
    echo "============================================"
    echo

    [[ -n "${INSTALL_PATH}" ]] || { integrity_error "INSTALL_PATH não definido."; return 1; }
    [[ -n "${EXECUTABLE}" ]] || { integrity_error "EXECUTABLE não definido."; return 1; }

    EXEC_PATH="${INSTALL_PATH}/${EXECUTABLE}"
    case "${ARTIFACT_MODE}" in file|java|jar) LABEL="Artefato" ;; esac

    echo "Installation:"
    echo "${INSTALL_PATH}"
    echo

    if integrity_check_directory "${INSTALL_PATH}"
    then
        echo "[OK] Diretório da instalação"
    else
        echo "[ERRO] Diretório da instalação ausente"
        STATUS="unhealthy"
    fi

    if integrity_check_artifact "${EXEC_PATH}" "${ARTIFACT_MODE}"
    then
        echo "[OK] ${LABEL}"
    else
        echo "[ERRO] ${LABEL} ausente ou inválido:"
        echo "${EXEC_PATH}"
        STATUS="unhealthy"
    fi

    if [[ "${STATUS}" != "healthy" ]]
    then
        echo
        echo "Status: unhealthy"
        echo
        return 1
    fi

    if ! integrity_provider_verify "${PACKAGE_ID}" "${INSTALL_PATH}" "${EXECUTABLE}"
    then
        STATUS="unhealthy"
    fi

    echo
    echo "Status: ${STATUS}"
    echo
    [[ "${STATUS}" == "healthy" ]]
}

export -f integrity_check_directory integrity_check_file integrity_check_executable integrity_check_artifact
export -f integrity_provider_verify integrity_validate
