#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Atomic Installation Progress Wrapper
#
# Instrumenta as funções já carregadas pelo Atomic Engine sem
# duplicar sua implementação. Os marcos são publicados quando
# as etapas reais acontecem: provider, validação, ativação e
# rollback.
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/installer/operation_progress.sh"

atomic_progress_integrity_wrapper()
{
    if ! declare -F integrity_validate >/dev/null 2>&1
    then
        return 0
    fi

    if declare -F integrity_validate_base >/dev/null 2>&1
    then
        return 0
    fi

    local ORIGINAL
    ORIGINAL="$(declare -f integrity_validate)"
    ORIGINAL="${ORIGINAL/integrity_validate ()/integrity_validate_base ()}"
    eval "${ORIGINAL}"

    integrity_validate()
    {
        DSM_ATOMIC_INTEGRITY_PASS="${DSM_ATOMIC_INTEGRITY_PASS:-0}"
        DSM_ATOMIC_INTEGRITY_PASS=$((DSM_ATOMIC_INTEGRITY_PASS + 1))

        if (( DSM_ATOMIC_INTEGRITY_PASS == 1 ))
        then
            install_operation_progress_safe "validating" 78 "Validando staging"
        else
            install_operation_progress_safe "validating" 95 "Validação final da instalação ativa"
        fi

        if integrity_validate_base "$@"
        then
            if (( DSM_ATOMIC_INTEGRITY_PASS == 1 ))
            then
                install_operation_progress_safe "activating" 88 "Staging validado; preparando ativação"
            else
                install_operation_progress_safe "finalizing" 98 "Instalação validada; finalizando"
            fi
            return 0
        fi

        return 1
    }

    export -f integrity_validate_base
    export -f integrity_validate
}

atomic_progress_rollback_wrapper()
{
    if ! declare -F install_rollback >/dev/null 2>&1
    then
        return 0
    fi

    if declare -F install_rollback_base >/dev/null 2>&1
    then
        return 0
    fi

    local ORIGINAL
    ORIGINAL="$(declare -f install_rollback)"
    ORIGINAL="${ORIGINAL/install_rollback ()/install_rollback_base ()}"
    eval "${ORIGINAL}"

    install_rollback()
    {
        install_operation_progress_safe "rollback" 92 "Restaurando versão anterior"

        if install_rollback_base "$@"
        then
            install_operation_progress_safe "validating" 96 "Validando versão restaurada"
            return 0
        fi

        return 1
    }

    export -f install_rollback_base
    export -f install_rollback
}

atomic_progress_install_wrapper()
{
    if ! declare -F atomic_install >/dev/null 2>&1
    then
        return 1
    fi

    if declare -F atomic_install_base >/dev/null 2>&1
    then
        return 0
    fi

    local ORIGINAL
    ORIGINAL="$(declare -f atomic_install)"
    ORIGINAL="${ORIGINAL/atomic_install ()/atomic_install_base ()}"
    eval "${ORIGINAL}"

    atomic_install()
    {
        local PROVIDER="${1:-unknown}"

        DSM_ATOMIC_INTEGRITY_PASS=0
        export DSM_ATOMIC_INTEGRITY_PASS

        install_operation_progress_safe "preparing" 10 "Preparando instalação atômica"
        install_operation_progress_safe "staging" 15 "Preparando staging"
        install_operation_progress_safe "downloading" 20 "Obtendo arquivos via ${PROVIDER}"

        if atomic_install_base "$@"
        then
            return 0
        fi

        case "${DSM_ATOMIC_ERROR:-unknown}" in
            staging_validation_failed|post_activation_validation_failed)
                install_operation_progress_safe "validating" 78 "Falha durante validação"
            ;;
            activation_failed|activation_restore_failed)
                install_operation_progress_safe "activating" 88 "Falha durante ativação"
            ;;
            automatic_rollback_failed)
                install_operation_progress_safe "rollback" 92 "Falha durante rollback automático"
            ;;
            provider_install_failed)
                install_operation_progress_safe "downloading" 25 "Falha ao obter arquivos"
            ;;
            *)
                install_operation_progress_safe "processing" 20 "Falha na operação atômica"
            ;;
        esac

        return 1
    }

    export -f atomic_install_base
    export -f atomic_install
}

atomic_progress_integrity_wrapper
atomic_progress_rollback_wrapper
atomic_progress_install_wrapper

export -f atomic_progress_integrity_wrapper
export -f atomic_progress_rollback_wrapper
export -f atomic_progress_install_wrapper
