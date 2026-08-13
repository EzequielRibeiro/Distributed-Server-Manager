#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Installation Error Handler
#
# Responsável por:
#
# - interpretar DSM_ATOMIC_ERROR
# - classificar falhas do Atomic Installation Engine
# - definir status final da instalação
# - publicar estado persistente
# - emitir eventos de validação
# - emitir evento final da operação
#
# Este arquivo NÃO executa:
#
# - instalação
# - update
# - rollback
# - download
# - provider
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# =============================================================
# Logger
# =============================================================

install_error_log()
{
    echo "[DSM][INSTALL-ERROR] $*"
}

install_error_error()
{
    echo "[DSM][INSTALL-ERROR][ERRO] $*" >&2
}

# =============================================================
# Determinar evento final
# =============================================================

install_error_final_event()
{
    local ACTION="${1:-}"

    case "${ACTION}" in

        install)
            echo "install_event_install_failed"
        ;;

        update)
            echo "install_event_update_failed"
        ;;

        rollback)
            echo "install_event_rollback_failed"
        ;;

        *)
            return 1
        ;;

    esac
}

# =============================================================
# Status padrão da instalação
#
# IMPORTANTE:
#
# Falha operacional não significa necessariamente instalação
# unhealthy.
#
# Exemplo:
#
# provider_install_failed
#
# ocorre antes da ativação do staging, portanto a instalação
# anterior permanece saudável.
#
# =============================================================

install_error_default_status()
{
    local ACTION="${1:-}"

    case "${ACTION}" in

        install)

            if [[ -d "${INSTALL_DIR:-}" ]]
            then
                echo "healthy"
            else
                echo "unhealthy"
            fi
        ;;

        update)
            echo "healthy"
        ;;

        rollback)
            echo "unhealthy"
        ;;

        *)
            echo "unhealthy"
        ;;

    esac
}

# =============================================================
# Emitir evento de validação
# =============================================================

install_error_validation_event()
{
    local GAME_ID="$1"
    local PROVIDER="$2"
    local VERSION="$3"
    local REASON="$4"

    if ! declare -F install_manager_event >/dev/null
    then
        return 0
    fi

    install_manager_event \
        install_event_validation_failed \
        "${GAME_ID}" \
        "${PROVIDER}" \
        "${VERSION}" \
        "${REASON}"
}

# =============================================================
# Publicar evento final
# =============================================================

install_error_final_event_emit()
{
    local EVENT_FUNCTION="$1"
    local GAME_ID="$2"
    local PROVIDER="$3"
    local REASON="$4"

    if [[ -z "${EVENT_FUNCTION}" ]]
    then
        return 0
    fi

    if ! declare -F install_manager_event >/dev/null
    then
        return 0
    fi

    install_manager_event \
        "${EVENT_FUNCTION}" \
        "${GAME_ID}" \
        "${PROVIDER}" \
        "${REASON}"
}

# =============================================================
# Atomic Error Handler
#
# Uso:
#
# install_error_handle_atomic \
#     ACTION \
#     GAME_ID \
#     PROVIDER \
#     PREVIOUS_VERSION
#
# ACTION:
#
# install
# update
#
# =============================================================

install_error_handle_atomic()
{
    local ACTION="${1:-}"
    local GAME_ID="${2:-}"
    local PROVIDER="${3:-unknown}"
    local PREVIOUS_VERSION="${4:-unknown}"

    local ERROR_CODE="${DSM_ATOMIC_ERROR:-unknown}"

    local INSTALL_STATUS
    local FINAL_EVENT
    local REASON
    local VALIDATION_VERSION

    INSTALL_STATUS="$(
        install_error_default_status \
            "${ACTION}"
    )"

    FINAL_EVENT="$(
        install_error_final_event \
            "${ACTION}" \
            2>/dev/null || true
    )"

    REASON="${ERROR_CODE}"
    VALIDATION_VERSION="${PREVIOUS_VERSION}"

    # =========================================================
    # Validar ação
    # =========================================================

    if [[ -z "${FINAL_EVENT}" ]]
    then
        install_error_error \
            "Ação não suportada pelo error handler: ${ACTION}"

        return 1
    fi

    # =========================================================
    # Classificação
    # =========================================================

    case "${ERROR_CODE}" in

        # -----------------------------------------------------
        # Provider não encontrado/carregado
        # -----------------------------------------------------

        provider_load_failed)

            REASON="provider_load_failed"
        ;;

        # -----------------------------------------------------
        # Provider indisponível
        # -----------------------------------------------------

        provider_unavailable)

            REASON="provider_unavailable"
        ;;

        # -----------------------------------------------------
        # Download / instalação do provider falhou
        #
        # Staging nunca chegou à ativação.
        # -----------------------------------------------------

        provider_install_failed)

            REASON="provider_install_failed"
        ;;

        # -----------------------------------------------------
        # Não foi possível limpar staging anterior
        # -----------------------------------------------------

        staging_cleanup_failed)

            REASON="staging_cleanup_failed"
        ;;

        # -----------------------------------------------------
        # Staging falhou na validação
        #
        # Instalação ativa permanece preservada.
        # -----------------------------------------------------

        staging_validation_failed)

            REASON="staging_validation_failed"

            install_error_validation_event \
                "${GAME_ID}" \
                "${PROVIDER}" \
                "${VALIDATION_VERSION}" \
                "${REASON}"
        ;;

        # -----------------------------------------------------
        # Não conseguiu preservar instalação atual em .old
        # -----------------------------------------------------

        preserve_current_failed)

            REASON="preserve_current_failed"
        ;;

        # -----------------------------------------------------
        # Falha no .new -> instalação ativa
        #
        # Atomic Engine tenta restaurar .old.
        # -----------------------------------------------------

        activation_failed)

            REASON="activation_failed"
        ;;

        # -----------------------------------------------------
        # Falha na ativação + falha na restauração
        #
        # Estado crítico.
        # -----------------------------------------------------

        activation_restore_failed)

            REASON="activation_restore_failed"
            INSTALL_STATUS="unhealthy"
        ;;

        # -----------------------------------------------------
        # Nova versão foi ativada mas falhou na validação final
        # -----------------------------------------------------

        post_activation_validation_failed)

            REASON="post_activation_validation_failed"

            install_error_validation_event \
                "${GAME_ID}" \
                "${PROVIDER}" \
                "${VALIDATION_VERSION}" \
                "${REASON}"
        ;;

        # -----------------------------------------------------
        # Rollback automático falhou
        #
        # Estado crítico.
        # -----------------------------------------------------

        automatic_rollback_failed)

            REASON="automatic_rollback_failed"
            INSTALL_STATUS="unhealthy"
        ;;

        # -----------------------------------------------------
        # Nenhum código conhecido
        # -----------------------------------------------------

        unknown|"")

            REASON="atomic_${ACTION}_failed"
        ;;

        # -----------------------------------------------------
        # Compatibilidade futura
        # -----------------------------------------------------

        *)

            REASON="${ERROR_CODE}"
        ;;

    esac

    # =========================================================
    # Publicar estado
    # =========================================================

    if declare -F install_manager_publish_state >/dev/null
    then
        install_manager_publish_state \
            "${GAME_ID}" \
            "${ACTION}" \
            "failed" \
            "${INSTALL_STATUS}"
    fi

    # =========================================================
    # Evento final
    # =========================================================

    install_error_final_event_emit \
        "${FINAL_EVENT}" \
        "${GAME_ID}" \
        "${PROVIDER}" \
        "${REASON}"

    install_error_log \
        "action=${ACTION} error=${ERROR_CODE} status=${INSTALL_STATUS}"

    return 0
}


# =============================================================
# Rollback Error Handler
#
# Responsável por:
#
# - classificar falhas específicas de rollback
# - definir status final da instalação
# - emitir INSTALL_VALIDATION_FAILED quando necessário
# - emitir ROLLBACK_FAILED
# - publicar estado persistente
#
# Uso:
#
# install_error_handle_rollback \
#     GAME_ID \
#     PROVIDER \
#     ERROR_CODE \
#     CURRENT_VERSION \
#     RESTORED_VERSION
#
# CURRENT_VERSION:
#   versão ativa antes do rollback
#
# RESTORED_VERSION:
#   versão restaurada, quando aplicável
#
# =============================================================

install_error_handle_rollback()
{
    local GAME_ID="${1:-}"
    local PROVIDER="${2:-unknown}"
    local ERROR_CODE="${3:-unknown}"
    local CURRENT_VERSION="${4:-unknown}"
    local RESTORED_VERSION="${5:-unknown}"

    local INSTALL_STATUS="unhealthy"
    local REASON="${ERROR_CODE}"

    # ---------------------------------------------------------
    # Validar argumentos
    # ---------------------------------------------------------

    if [[ -z "${GAME_ID}" ]]
    then
        install_error_error "GAME_ID não informado no rollback handler."
        return 1
    fi

    # =========================================================
    # Classificação
    # =========================================================

    case "${ERROR_CODE}" in

        # -----------------------------------------------------
        # Não existe .old
        #
        # Nada foi alterado na instalação ativa.
        # Portanto ela continua saudável.
        # -----------------------------------------------------

        rollback_not_available)

            REASON="rollback_not_available"
            INSTALL_STATUS="healthy"
        ;;

        # -----------------------------------------------------
        # Rollback Engine falhou durante movimentação.
        #
        # Estado pode estar inconsistente.
        # -----------------------------------------------------

        rollback_operation_failed)

            REASON="rollback_operation_failed"
            INSTALL_STATUS="unhealthy"
        ;;

        # -----------------------------------------------------
        # Provider não disponível após rollback
        #
        # Não conseguimos verificar corretamente a instalação
        # restaurada.
        # -----------------------------------------------------

        provider_unavailable)

            REASON="provider_unavailable"
            INSTALL_STATUS="unhealthy"
        ;;

        # -----------------------------------------------------
        # Versão restaurada falhou no Integrity Engine
        # -----------------------------------------------------

        rollback_integrity_failed|rollback_validation_failed)

            REASON="rollback_validation_failed"
            INSTALL_STATUS="unhealthy"

            install_error_validation_event \
                "${GAME_ID}" \
                "${PROVIDER}" \
                "${RESTORED_VERSION}" \
                "rollback_integrity_failed"
        ;;

        # -----------------------------------------------------
        # Código não reconhecido
        # -----------------------------------------------------

        unknown|"")

            REASON="rollback_failed"
            INSTALL_STATUS="unhealthy"
        ;;

        *)

            REASON="${ERROR_CODE}"
            INSTALL_STATUS="unhealthy"
        ;;

    esac

    # =========================================================
    # Estado persistente
    # =========================================================

    if declare -F install_manager_publish_state >/dev/null
    then
        install_manager_publish_state \
            "${GAME_ID}" \
            "rollback" \
            "failed" \
            "${INSTALL_STATUS}"
    fi

    # =========================================================
    # Evento final
    # =========================================================

    if declare -F install_manager_event >/dev/null
    then
        install_manager_event \
            install_event_rollback_failed \
            "${GAME_ID}" \
            "${PROVIDER}" \
            "${REASON}"
    fi

    # =========================================================
    # Log
    # =========================================================

    install_error_log \
        "action=rollback error=${ERROR_CODE} status=${INSTALL_STATUS} current=${CURRENT_VERSION} restored=${RESTORED_VERSION}"

    return 0
}


# =============================================================
# Export API
# =============================================================

export -f install_error_log
export -f install_error_error

export -f install_error_final_event
export -f install_error_default_status
export -f install_error_validation_event
export -f install_error_final_event_emit
export -f install_error_handle_rollback
export -f install_error_handle_atomic