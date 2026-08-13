#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Atomic Installation Manager
#
# Responsável por:
#
# - instalar através de um Provider
# - utilizar staging (.new)
# - validar antes da ativação
# - preservar instalação anterior (.old)
# - realizar troca atômica
# - realizar rollback em caso de falha
#
# IMPORTANTE:
#
# Este arquivo NÃO conhece SteamCMD diretamente.
#
# O Provider é responsável por obter os arquivos:
#
#   steam
#   http
#   github
#   local
#   custom
#
# Fluxo:
#
# Provider
#    ↓
# serverfiles.new
#    ↓
# Integrity Check
#    ↓
# serverfiles → serverfiles.old
#    ↓
# serverfiles.new → serverfiles
#    ↓
# Final Validation
#    ↓
# Rollback se necessário
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/installer/integrity.sh"
source "${DSM_ROOT}/installer/buildid.sh"
source "${DSM_ROOT}/installer/rollback.sh"
source "${DSM_ROOT}/installer/provider_loader.sh"

atomic_log()
{
    echo "[DSM][ATOMIC] $*"
}

atomic_error()
{
    echo "[DSM][ATOMIC][ERRO] $*" >&2
}

atomic_cleanup_staging()
{
    local STAGING="$1"

    if [[ -z "${STAGING}" || "${STAGING}" == "/" ]]
    then
        atomic_error "Staging inválido."
        return 1
    fi

    if [[ -d "${STAGING}" ]]
    then
        atomic_log "Removendo staging anterior:"
        atomic_log "${STAGING}"
        rm -rf -- "${STAGING}"
    fi
}

atomic_validate_arguments()
{
    local PROVIDER="$1"
    local GAME_ID="$2"
    local PACKAGE_ID="$3"
    local INSTALL_PATH="$4"
    local EXECUTABLE="$5"

    if [[ -z "${PROVIDER}" ]]
    then
        atomic_error "Provider não definido."
        return 1
    fi

    if [[ -z "${GAME_ID}" ]]
    then
        atomic_error "Game ID não definido."
        return 1
    fi

    if [[ -z "${PACKAGE_ID}" ]]
    then
        atomic_error "Package/App ID não definido."
        return 1
    fi

    if [[ -z "${INSTALL_PATH}" || "${INSTALL_PATH}" == "/" ]]
    then
        atomic_error "Diretório de instalação inválido."
        return 1
    fi

    if [[ -z "${EXECUTABLE}" ]]
    then
        atomic_error "Executável não definido."
        return 1
    fi

    DSM_ATOMIC_ERROR=""
    export DSM_ATOMIC_ERROR
    return 0
}

atomic_provider_version()
{
    local PACKAGE_ID="$1"
    local INSTALL_PATH="$2"
    local VERSION=""

    if declare -F provider_version >/dev/null
    then
        VERSION="$(provider_version "${PACKAGE_ID}" "${INSTALL_PATH}" 2>/dev/null || true)"
    fi

    [[ -n "${VERSION}" ]] || VERSION="unknown"
    echo "${VERSION}"
}

atomic_install()
{
    DSM_ATOMIC_ERROR=""
    export DSM_ATOMIC_ERROR

    local PROVIDER="${1:-}"
    local GAME_ID="${2:-}"
    local PACKAGE_ID="${3:-}"
    local INSTALL_PATH="${4:-}"
    local EXECUTABLE="${5:-}"
    local INSTALL_USER="${6:-anonymous}"
    local NEW_PATH OLD_PATH
    local OLD_VERSION="" NEW_VERSION=""

    NEW_PATH="${INSTALL_PATH}.new"
    OLD_PATH="${INSTALL_PATH}.old"

    echo
    echo "============================================"
    echo " Capivara - Atomic Installation"
    echo "============================================"
    echo

    atomic_validate_arguments \
        "${PROVIDER}" \
        "${GAME_ID}" \
        "${PACKAGE_ID}" \
        "${INSTALL_PATH}" \
        "${EXECUTABLE}" || return 1

    atomic_log "Game       : ${GAME_ID}"
    atomic_log "Provider   : ${PROVIDER}"
    atomic_log "Package ID : ${PACKAGE_ID}"
    atomic_log "Install    : ${INSTALL_PATH}"
    atomic_log "Temporary  : ${NEW_PATH}"
    echo

    atomic_log "Carregando provider..."
    if ! provider_require "${PROVIDER}"
    then
        DSM_ATOMIC_ERROR="provider_load_failed"
        export DSM_ATOMIC_ERROR
        atomic_error "Não foi possível carregar provider: ${PROVIDER}"
        return 1
    fi

    atomic_log "Preparando provider..."
    if ! provider_ensure
    then
        DSM_ATOMIC_ERROR="provider_unavailable"
        export DSM_ATOMIC_ERROR
        atomic_error "Provider indisponível: ${PROVIDER}"
        return 1
    fi

    if [[ -d "${INSTALL_PATH}" ]]
    then
        OLD_VERSION="$(atomic_provider_version "${PACKAGE_ID}" "${INSTALL_PATH}")"
        atomic_log "Versão atual: ${OLD_VERSION}"
    fi

    if ! atomic_cleanup_staging "${NEW_PATH}"
    then
        DSM_ATOMIC_ERROR="staging_cleanup_failed"
        export DSM_ATOMIC_ERROR
        return 1
    fi

    mkdir -p "$(dirname "${INSTALL_PATH}")"
    mkdir -p "${NEW_PATH}"

    echo
    atomic_log "Instalando no staging..."

    DSM_EXPECTED_EXECUTABLE="${EXECUTABLE}"
    export DSM_EXPECTED_EXECUTABLE

    if ! provider_install \
        "${PACKAGE_ID}" \
        "${NEW_PATH}" \
        "${INSTALL_USER}"
    then
        unset DSM_EXPECTED_EXECUTABLE
        DSM_ATOMIC_ERROR="provider_install_failed"
        export DSM_ATOMIC_ERROR
        atomic_error "Provider falhou durante a instalação."
        atomic_cleanup_staging "${NEW_PATH}"
        return 1
    fi

    unset DSM_EXPECTED_EXECUTABLE

    echo
    atomic_log "Validando nova instalação..."

    if ! integrity_validate \
        "${NEW_PATH}" \
        "${PACKAGE_ID}" \
        "${EXECUTABLE}"
    then
        DSM_ATOMIC_ERROR="staging_validation_failed"
        export DSM_ATOMIC_ERROR
        atomic_error "Nova instalação falhou na validação."
        atomic_log "Instalação atual será preservada."
        atomic_cleanup_staging "${NEW_PATH}"
        return 1
    fi

    NEW_VERSION="$(atomic_provider_version "${PACKAGE_ID}" "${NEW_PATH}")"
    atomic_log "Nova versão: ${NEW_VERSION}"

    if [[ -d "${OLD_PATH}" ]]
    then
        atomic_log "Removendo rollback anterior:"
        atomic_log "${OLD_PATH}"
        rm -rf -- "${OLD_PATH}"
    fi

    if [[ -d "${INSTALL_PATH}" ]]
    then
        echo
        atomic_log "Preservando instalação atual:"
        atomic_log "${OLD_PATH}"

        if ! mv -- "${INSTALL_PATH}" "${OLD_PATH}"
        then
            DSM_ATOMIC_ERROR="preserve_current_failed"
            export DSM_ATOMIC_ERROR
            atomic_error "Não foi possível preservar a instalação atual."
            atomic_cleanup_staging "${NEW_PATH}"
            return 1
        fi
    fi

    echo
    atomic_log "Ativando nova instalação..."

    if ! mv -- "${NEW_PATH}" "${INSTALL_PATH}"
    then
        DSM_ATOMIC_ERROR="activation_failed"
        export DSM_ATOMIC_ERROR
        atomic_error "Falha ao ativar nova instalação."

        if [[ -d "${OLD_PATH}" ]]
        then
            atomic_log "Restaurando instalação anterior..."
            if ! mv -- "${OLD_PATH}" "${INSTALL_PATH}"
            then
                DSM_ATOMIC_ERROR="activation_restore_failed"
                export DSM_ATOMIC_ERROR
                atomic_error "Falha crítica durante restauração."
                return 1
            fi
        fi
        return 1
    fi

    echo
    atomic_log "Executando validação final..."

    if ! integrity_validate \
        "${INSTALL_PATH}" \
        "${PACKAGE_ID}" \
        "${EXECUTABLE}"
    then
        DSM_ATOMIC_ERROR="post_activation_validation_failed"
        export DSM_ATOMIC_ERROR
        atomic_error "Nova instalação falhou após ativação."

        if [[ -d "${OLD_PATH}" ]]
        then
            atomic_log "Executando rollback..."
            if ! install_rollback "${INSTALL_PATH}"
            then
                DSM_ATOMIC_ERROR="automatic_rollback_failed"
                export DSM_ATOMIC_ERROR
                atomic_error "Rollback falhou."
                return 1
            fi
        fi
        return 1
    fi

    echo
    echo "============================================"
    echo " Instalação concluída"
    echo "============================================"
    echo
    echo "Game     : ${GAME_ID}"
    echo "Provider : ${PROVIDER}"

    if [[ -n "${OLD_VERSION}" ]]
    then
        echo "Anterior : ${OLD_VERSION}"
    fi

    echo "Versão   : ${NEW_VERSION}"
    echo "Status   : healthy"

    if [[ -d "${OLD_PATH}" ]]
    then
        echo "Rollback : disponível"
    else
        echo "Rollback : indisponível"
    fi

    echo
    DSM_ATOMIC_ERROR=""
    export DSM_ATOMIC_ERROR
    return 0
}

export -f atomic_cleanup_staging
export -f atomic_validate_arguments
export -f atomic_install
