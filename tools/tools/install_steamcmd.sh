#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Atomic Install Engine
#
# Responsável:
#
# Realizar instalação/atualização atômica de servidores.
#
# O Atomic Install não conhece SteamCMD, HTTP, GitHub etc.
# Toda obtenção dos arquivos é delegada ao Provider.
#
# Fluxo:
#
#   provider
#      ↓
#   staging
#      ↓
#   integrity check
#      ↓
#   build identification
#      ↓
#   atomic switch
#      ↓
#   final validation
#      ↓
#   rollback automático em caso de falha
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# =============================================================
# Dependências
# =============================================================

source "${DSM_ROOT}/installer/provider.sh"
source "${DSM_ROOT}/installer/integrity.sh"
source "${DSM_ROOT}/installer/buildid.sh"


# =============================================================
# Log
# =============================================================

atomic_log()
{
    echo "[DSM][ATOMIC] $*"
}


atomic_error()
{
    echo "[DSM][ATOMIC][ERRO] $*" >&2
}


# =============================================================
# Limpeza de staging
# =============================================================

atomic_cleanup_staging()
{
    local STAGING="$1"

    if [[ -d "${STAGING}" ]]
    then
        atomic_log "Removendo staging:"
        atomic_log "${STAGING}"

        rm -rf -- "${STAGING}"
    fi
}


# =============================================================
# Rollback
# =============================================================

atomic_rollback()
{
    local INSTALL_DIR="$1"
    local OLD_DIR="$2"

    atomic_log "Executando rollback..."

    if [[ -d "${INSTALL_DIR}" ]]
    then
        rm -rf -- "${INSTALL_DIR}"
    fi

    if [[ ! -d "${OLD_DIR}" ]]
    then
        atomic_error "Instalação anterior não encontrada."
        atomic_error "Rollback impossível."

        return 1
    fi

    mv -- "${OLD_DIR}" "${INSTALL_DIR}"

    atomic_log "Rollback concluído."

    return 0
}


# =============================================================
# Instalação atômica
#
# Uso:
#
# atomic_install \
#     steam \
#     dayz \
#     223350 \
#     /opt/dsm/game-data/dayz/serverfiles \
#     DayZServer
#
# Argumentos:
#
# $1 = Provider
# $2 = Game ID
# $3 = Package/App ID
# $4 = Diretório final
# $5 = Executável esperado
#
# =============================================================

atomic_install()
{
    local PROVIDER="$1"
    local GAME_ID="$2"
    local PACKAGE_ID="$3"
    local INSTALL_DIR="$4"
    local EXECUTABLE="$5"
    local INSTALL_USER="${6:-anonymous}"

    local STAGING
    local OLD_DIR

    local NEW_BUILD=""
    local OLD_BUILD=""

    STAGING="${INSTALL_DIR}.new"
    OLD_DIR="${INSTALL_DIR}.old"


    echo
    echo "============================================"
    echo " Capivara - Atomic Install"
    echo "============================================"
    echo

    atomic_log "Game       : ${GAME_ID}"
    atomic_log "Provider   : ${PROVIDER}"
    atomic_log "Package ID : ${PACKAGE_ID}"
    atomic_log "Destino    : ${INSTALL_DIR}"
    atomic_log "Staging    : ${STAGING}"

    echo


    # =========================================================
    # Segurança básica
    # =========================================================

    if [[ -z "${INSTALL_DIR}" || "${INSTALL_DIR}" == "/" ]]
    then
        atomic_error "Diretório de instalação inválido."

        return 1
    fi


    # =========================================================
    # Provider
    # =========================================================

    atomic_log "Preparando provider..."

    if ! provider_ensure
    then
        atomic_error "Provider indisponível: ${PROVIDER}"

        return 1
    fi


    # =========================================================
    # Build atual
    # =========================================================

    if [[ -d "${INSTALL_DIR}" ]]
    then
        OLD_BUILD="$(
            install_buildid \
                "${INSTALL_DIR}" \
                "${PACKAGE_ID}" \
                2>/dev/null || true
        )"

        if [[ -n "${OLD_BUILD}" ]]
        then
            atomic_log "Build atual: ${OLD_BUILD}"
        fi
    fi


    # =========================================================
    # Preparar staging
    # =========================================================

    atomic_cleanup_staging "${STAGING}"

    mkdir -p "$(dirname "${INSTALL_DIR}")"
    mkdir -p "${STAGING}"


    # =========================================================
    # Download / instalação através do Provider
    # =========================================================

    atomic_log "Instalando no staging..."

    if ! provider_install \
         "${PACKAGE_ID}" \
         "${STAGING}" \
         "${INSTALL_USER}"
    then
        atomic_error "Provider falhou durante a instalação."

        atomic_cleanup_staging "${STAGING}"

        return 1
    fi


    # =========================================================
    # Integridade do staging
    # =========================================================

    atomic_log "Validando staging..."

    if ! integrity_validate \
        "${STAGING}" \
        "${PACKAGE_ID}" \
        "${EXECUTABLE}"
    then
        atomic_error "Staging falhou na validação de integridade."

        atomic_cleanup_staging "${STAGING}"

        return 1
    fi


    # =========================================================
    # Build novo
    # =========================================================

    NEW_BUILD="$(
        install_buildid \
            "${STAGING}" \
            "${PACKAGE_ID}" \
            2>/dev/null || true
    )"

    if [[ -n "${NEW_BUILD}" ]]
    then
        atomic_log "Novo BuildID: ${NEW_BUILD}"
    else
        atomic_log "BuildID não disponível para esta instalação."
    fi


    # =========================================================
    # Remover backup antigo
    # =========================================================

    if [[ -d "${OLD_DIR}" ]]
    then
        atomic_log "Removendo instalação .old anterior..."

        rm -rf -- "${OLD_DIR}"
    fi


    # =========================================================
    # Preservar instalação atual
    # =========================================================

    if [[ -d "${INSTALL_DIR}" ]]
    then
        atomic_log "Preservando instalação atual..."

        mv -- "${INSTALL_DIR}" "${OLD_DIR}"
    fi


    # =========================================================
    # Atomic switch
    # =========================================================

    atomic_log "Ativando nova instalação..."

    if ! mv -- "${STAGING}" "${INSTALL_DIR}"
    then
        atomic_error "Falha ao ativar nova instalação."

        if [[ -d "${OLD_DIR}" ]]
        then
            atomic_rollback "${INSTALL_DIR}" "${OLD_DIR}"
        fi

        return 1
    fi


    # =========================================================
    # Validação após switch
    # =========================================================

    atomic_log "Executando validação final..."

    if ! integrity_validate \
        "${INSTALL_DIR}" \
        "${PACKAGE_ID}" \
        "${EXECUTABLE}"
    then
        atomic_error "Nova instalação falhou após ativação."

        if [[ -d "${OLD_DIR}" ]]
        then
            atomic_rollback "${INSTALL_DIR}" "${OLD_DIR}"
        fi

        return 1
    fi


    # =========================================================
    # Resultado
    # =========================================================

    echo
    echo "============================================"
    echo " Atomic Install concluído"
    echo "============================================"
    echo

    atomic_log "Game     : ${GAME_ID}"

    if [[ -n "${OLD_BUILD}" ]]
    then
        atomic_log "Anterior : ${OLD_BUILD}"
    fi

    if [[ -n "${NEW_BUILD}" ]]
    then
        atomic_log "Atual    : ${NEW_BUILD}"
    fi

    atomic_log "Status   : healthy"

    echo

    return 0
}


export -f atomic_install
export -f atomic_rollback
export -f atomic_cleanup_staging