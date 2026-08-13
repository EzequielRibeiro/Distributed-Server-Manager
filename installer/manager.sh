#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Universal Installation Manager
#
# Responsável por:
#
# - carregar configuração do jogo
# - carregar configuração do provider
# - executar instalação atômica
# - executar atualização
# - validar instalação
# - executar rollback
# - publicar estado persistente
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# =============================================================
# Dependências
# =============================================================

source "${DSM_ROOT}/installer/atomic_install.sh"
source "${DSM_ROOT}/installer/atomic_progress.sh"
source "${DSM_ROOT}/installer/integrity.sh"
source "${DSM_ROOT}/installer/rollback.sh"
source "${DSM_ROOT}/installer/provider_loader.sh"
source "${DSM_ROOT}/installer/state.sh"
source "${DSM_ROOT}/installer/events.sh"
source "${DSM_ROOT}/installer/error_handler.sh"

# =============================================================
# Logger
# =============================================================

install_manager_log()
{
    echo "[DSM][INSTALL] $*"
}

install_manager_error()
{
    echo "[DSM][INSTALL][ERRO] $*" >&2
}

# =============================================================
# Game Config
# =============================================================

install_manager_game_config()
{
    local GAME_ID="$1"

    echo "${DSM_ROOT}/games/${GAME_ID}/game.conf"
}

# =============================================================
# Provider Config
# =============================================================

install_manager_provider_config()
{
    local PROVIDER="$1"

    echo "${DSM_ROOT}/config/providers/${PROVIDER}.conf"
}

# =============================================================
# Carregar configuração do provider
# =============================================================

install_manager_load_provider_config()
{
    local PROVIDER="$1"
    local CONF

    CONF="$(install_manager_provider_config "${PROVIDER}")"

    if [[ ! -f "${CONF}" ]]
    then
        return 0
    fi

    unset STEAM_USER 2>/dev/null || true

    # shellcheck source=/dev/null
    source "${CONF}"

    return 0
}

# =============================================================
# Carregar jogo
# =============================================================

install_manager_load_game()
{
    local GAME_ID="$1"
    local CONF

    CONF="$(install_manager_game_config "${GAME_ID}")"

    if [[ ! -f "${CONF}" ]]
    then
        install_manager_error "Jogo não registrado:"
        install_manager_error "${GAME_ID}"
        return 1
    fi

    unset GAME_NAME 2>/dev/null || true
    unset INSTALL_PROVIDER 2>/dev/null || true
    unset INSTALL_PACKAGE_ID 2>/dev/null || true
    unset INSTALL_DIR 2>/dev/null || true
    unset EXECUTABLE 2>/dev/null || true
    unset INSTALL_AUTH 2>/dev/null || true
    unset GAME_VARIANT 2>/dev/null || true
    unset GAME_VERSION 2>/dev/null || true
    unset GAME_BUILD 2>/dev/null || true

    # shellcheck source=/dev/null
    source "${CONF}"

    if [[ -z "${INSTALL_PROVIDER:-}" ]]
    then
        install_manager_error "INSTALL_PROVIDER não definido."
        return 1
    fi

    if [[ -z "${INSTALL_PACKAGE_ID:-}" ]]
    then
        install_manager_error "INSTALL_PACKAGE_ID não definido."
        return 1
    fi

    if [[ -z "${INSTALL_DIR:-}" ]]
    then
        install_manager_error "INSTALL_DIR não definido."
        return 1
    fi

    if [[ -z "${EXECUTABLE:-}" ]]
    then
        install_manager_error "EXECUTABLE não definido."
        return 1
    fi

    return 0
}

install_manager_resolve_user()
{
    local PROVIDER="${INSTALL_PROVIDER:-}"
    local AUTH="${INSTALL_AUTH:-anonymous}"
    local USER=""

    if [[ -n "${DSM_INSTALL_USER:-}" ]]
    then
        echo "${DSM_INSTALL_USER}"
        return 0
    fi

    install_manager_load_provider_config "${PROVIDER}"

    case "${PROVIDER}" in
        steam)
            if [[ -n "${STEAM_USER:-}" ]]
            then
                USER="${STEAM_USER}"
            fi
        ;;
    esac

    if [[ -n "${USER}" ]]
    then
        echo "${USER}"
        return 0
    fi

    if [[ "${AUTH}" == "anonymous" ]]
    then
        echo "anonymous"
        return 0
    fi

    install_manager_error "Credencial não configurada para provider: ${PROVIDER}"
    return 1
}

install_manager_version()
{
    local PACKAGE_ID="$1"
    local INSTALL_PATH="$2"
    local VERSION="unknown"

    if declare -F provider_version >/dev/null
    then
        VERSION="$(provider_version "${PACKAGE_ID}" "${INSTALL_PATH}" 2>/dev/null || true)"
    fi

    [[ -n "${VERSION}" ]] || VERSION="unknown"
    echo "${VERSION}"
}

install_manager_rollback_status()
{
    local INSTALL_PATH="$1"

    if install_rollback_available "${INSTALL_PATH}"
    then
        echo "true"
    else
        echo "false"
    fi
}

install_manager_publish_state()
{
    local GAME_ID="$1"
    local ACTION="$2"
    local RESULT="$3"
    local STATUS="$4"

    local VERSION="unknown"
    local ROLLBACK="false"

    provider_require "${INSTALL_PROVIDER}" >/dev/null 2>&1 || true

    if [[ -d "${INSTALL_DIR}" ]]
    then
        VERSION="$(install_manager_provider_version "${INSTALL_PACKAGE_ID}" "${INSTALL_DIR}")"
    fi

    ROLLBACK="$(install_manager_rollback_status "${INSTALL_DIR}")"

    install_state_publish \
        "${GAME_ID}" \
        "${INSTALL_PROVIDER}" \
        "${VERSION}" \
        "${STATUS}" \
        "${ROLLBACK}" \
        "${ACTION}" \
        "${RESULT}"
}

install_manager_install()
{
    local GAME_ID="$1"
    local INSTALL_USER
    local PREVIOUS_VERSION="unknown"
    local VERSION="unknown"
    local ROLLBACK="false"

    install_manager_load_game "${GAME_ID}" || return 1
    INSTALL_USER="$(install_manager_resolve_user)" || return 1
    provider_require "${INSTALL_PROVIDER}" >/dev/null 2>&1 || true
    PREVIOUS_VERSION="$(install_manager_current_version)"

    echo
    echo "============================================"
    echo " Capivara - Game Install"
    echo "============================================"
    echo
    echo "Game     : ${GAME_NAME:-${GAME_ID}}"
    echo "Provider : ${INSTALL_PROVIDER}"
    echo "Variant  : ${GAME_VARIANT:-default}"
    echo "Version  : ${GAME_VERSION:-current}"
    echo "Destino  : ${INSTALL_DIR}"
    echo

    install_manager_publish_state "${GAME_ID}" "install" "running" "installing"
    install_manager_event install_event_install_started "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}"

    if atomic_install \
        "${INSTALL_PROVIDER}" \
        "${GAME_ID}" \
        "${INSTALL_PACKAGE_ID}" \
        "${INSTALL_DIR}" \
        "${EXECUTABLE}" \
        "${INSTALL_USER}"
    then
        VERSION="$(install_manager_current_version)"
        ROLLBACK="$(install_manager_rollback_status "${INSTALL_DIR}")"
        install_manager_publish_state "${GAME_ID}" "install" "success" "healthy"
        install_manager_event install_event_install_completed "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}" "${VERSION}" "${ROLLBACK}"
        return 0
    fi

    install_error_handle_atomic "install" "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}"
    return 1
}

install_manager_update()
{
    local GAME_ID="$1"
    local INSTALL_USER
    local PREVIOUS_VERSION="unknown"
    local VERSION="unknown"
    local ROLLBACK="false"

    install_manager_load_game "${GAME_ID}" || return 1
    INSTALL_USER="$(install_manager_resolve_user)" || return 1
    provider_require "${INSTALL_PROVIDER}" >/dev/null 2>&1 || true
    PREVIOUS_VERSION="$(install_manager_current_version)"

    echo
    echo "============================================"
    echo " Capivara - Game Update"
    echo "============================================"
    echo

    install_manager_publish_state "${GAME_ID}" "update" "running" "updating"
    install_manager_event install_event_update_started "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}"

    if atomic_install \
        "${INSTALL_PROVIDER}" \
        "${GAME_ID}" \
        "${INSTALL_PACKAGE_ID}" \
        "${INSTALL_DIR}" \
        "${EXECUTABLE}" \
        "${INSTALL_USER}"
    then
        VERSION="$(install_manager_current_version)"
        ROLLBACK="$(install_manager_rollback_status "${INSTALL_DIR}")"
        install_manager_publish_state "${GAME_ID}" "update" "success" "healthy"
        install_manager_event install_event_update_completed "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}" "${VERSION}" "${ROLLBACK}"
        return 0
    fi

    install_error_handle_atomic "update" "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}"
    return 1
}

install_manager_validate()
{
    local GAME_ID="$1"
    local VERSION="unknown"

    install_manager_load_game "${GAME_ID}" || return 1

    if ! provider_require "${INSTALL_PROVIDER}"
    then
        install_manager_publish_state "${GAME_ID}" "rollback" "failed" "unhealthy"
        install_manager_event install_event_rollback_failed "${GAME_ID}" "${INSTALL_PROVIDER}" "provider_unavailable"
        return 1
    fi

    VERSION="$(install_manager_current_version)"

    if ! integrity_validate "${INSTALL_DIR}" "${INSTALL_PACKAGE_ID}" "${EXECUTABLE}"
    then
        install_manager_publish_state "${GAME_ID}" "rollback" "failed" "unhealthy"
        install_manager_event install_event_validation_failed "${GAME_ID}" "${INSTALL_PROVIDER}" "${VERSION}" "rollback_integrity_failed"
        install_manager_event install_event_rollback_failed "${GAME_ID}" "${INSTALL_PROVIDER}" "rollback_validation_failed"
        return 1
    fi

    if integrity_validate "${INSTALL_DIR}" "${INSTALL_PACKAGE_ID}" "${EXECUTABLE}"
    then
        install_manager_publish_state "${GAME_ID}" "validate" "success" "healthy"
        return 0
    fi

    install_manager_publish_state "${GAME_ID}" "validate" "failed" "unhealthy"
    return 1
}

install_manager_rollback()
{
    local GAME_ID="$1"
    local PREVIOUS_VERSION="unknown"
    local VERSION="unknown"
    local ROLLBACK="false"

    install_manager_load_game "${GAME_ID}" || return 1
    provider_require "${INSTALL_PROVIDER}" >/dev/null 2>&1 || true
    PREVIOUS_VERSION="$(install_manager_current_version)"

    if ! install_rollback_available "${INSTALL_DIR}"
    then
        install_manager_error "Rollback não disponível."
        install_error_handle_rollback "${GAME_ID}" "${INSTALL_PROVIDER}" "rollback_not_available" "${PREVIOUS_VERSION}" "unknown"
        return 1
    fi

    install_manager_publish_state "${GAME_ID}" "rollback" "running" "rollback"
    install_manager_event install_event_rollback_started "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}"

    if ! install_rollback "${INSTALL_DIR}"
    then
        install_error_handle_rollback "${GAME_ID}" "${INSTALL_PROVIDER}" "rollback_operation_failed" "${PREVIOUS_VERSION}" "unknown"
        return 1
    fi

    if ! provider_require "${INSTALL_PROVIDER}"
    then
        install_error_handle_rollback "${GAME_ID}" "${INSTALL_PROVIDER}" "provider_unavailable" "${PREVIOUS_VERSION}" "unknown"
        return 1
    fi

    VERSION="$(install_manager_provider_version "${INSTALL_PACKAGE_ID}" "${INSTALL_DIR}")"

    if ! integrity_validate "${INSTALL_DIR}" "${INSTALL_PACKAGE_ID}" "${EXECUTABLE}"
    then
        install_error_handle_rollback "${GAME_ID}" "${INSTALL_PROVIDER}" "rollback_integrity_failed" "${PREVIOUS_VERSION}" "${VERSION}"
        return 1
    fi

    ROLLBACK="$(install_manager_rollback_status "${INSTALL_DIR}")"
    install_manager_publish_state "${GAME_ID}" "rollback" "success" "healthy"
    install_manager_event install_event_rollback_completed "${GAME_ID}" "${INSTALL_PROVIDER}" "${PREVIOUS_VERSION}" "${VERSION}" "${ROLLBACK}"
    return 0
}

install_manager_provider_version()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local VERSION="unknown"

    VERSION="$(provider_version "${PACKAGE_ID}" "${INSTALL_PATH}" 2>/dev/null || true)"
    [[ -n "${VERSION}" ]] || VERSION="unknown"
    echo "${VERSION}"
}

install_manager_info()
{
    local GAME_ID="$1"
    local VERSION="unknown"
    local STATUS="not-installed"
    local ROLLBACK="no"

    install_manager_load_game "${GAME_ID}" || return 1
    provider_require "${INSTALL_PROVIDER}" >/dev/null 2>&1 || true

    if [[ ! -d "${INSTALL_DIR}" ]]
    then
        STATUS="not-installed"
    else
        STATUS="installed"
        VERSION="$(install_manager_provider_version "${INSTALL_PACKAGE_ID}" "${INSTALL_DIR}")"
        if install_rollback_available "${INSTALL_DIR}"; then ROLLBACK="yes"; fi
    fi

    echo "game=${GAME_ID}"
    echo "provider=${INSTALL_PROVIDER}"
    echo "version=${VERSION}"
    echo "status=${STATUS}"
    echo "rollback=${ROLLBACK}"
}

install_manager_current_version()
{
    if [[ -z "${INSTALL_PROVIDER:-}" || -z "${INSTALL_PACKAGE_ID:-}" || -z "${INSTALL_DIR:-}" ]]
    then
        echo "unknown"
        return 0
    fi

    provider_require "${INSTALL_PROVIDER}" >/dev/null 2>&1 || true
    install_manager_provider_version "${INSTALL_PACKAGE_ID}" "${INSTALL_DIR}"
}

install_manager_event()
{
    local EVENT_FUNCTION="${1:-}"
    shift || true

    if [[ -z "${EVENT_FUNCTION}" ]]
    then
        return 0
    fi

    if declare -F "${EVENT_FUNCTION}" >/dev/null 2>&1
    then
        "${EVENT_FUNCTION}" "$@" || true
    fi
}

export -f install_manager_game_config
export -f install_manager_provider_config
export -f install_manager_load_provider_config
export -f install_manager_load_game
export -f install_manager_resolve_user
export -f install_manager_version
export -f install_manager_rollback_status
export -f install_manager_publish_state
export -f install_manager_install
export -f install_manager_update
export -f install_manager_validate
export -f install_manager_rollback
export -f install_manager_provider_version
export -f install_manager_info
export -f install_manager_current_version
export -f install_manager_event
