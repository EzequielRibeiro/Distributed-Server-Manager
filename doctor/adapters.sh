#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Doctor - Adapter Registry
#
# Responsável:
#   Selecionar os checks corretos para cada jogo/runtime.
#
# Regras:
#
#   minecraft -> generic + minecraft
#   dayz      -> generic + dayz
#   arma3     -> generic + arma3
#   demais    -> generic
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

DOCTOR_ADAPTER_DIR="${DSM_ROOT}/doctor/adapters"


doctor_adapter_normalize_game()
{
    local GAME="${1:-}"

    printf '%s\n' "${GAME,,}"
}


doctor_adapter_exists()
{
    local GAME
    GAME="$(doctor_adapter_normalize_game "${1:-}")"

    [[ -f "${DOCTOR_ADAPTER_DIR}/${GAME}.sh" ]]
}


doctor_adapter_load()
{
    local GAME
    GAME="$(doctor_adapter_normalize_game "${1:-}")"

    if [[ -z "${GAME}" ]]
    then
        echo "Game não informado." >&2
        return 1
    fi

    local GENERIC
    GENERIC="${DOCTOR_ADAPTER_DIR}/generic.sh"

    if [[ -f "${GENERIC}" ]]
    then
        # shellcheck source=/dev/null
        source "${GENERIC}"
    fi

    local ADAPTER
    ADAPTER="${DOCTOR_ADAPTER_DIR}/${GAME}.sh"

    if [[ -f "${ADAPTER}" ]]
    then
        # shellcheck source=/dev/null
        source "${ADAPTER}"
    fi

    return 0
}


doctor_adapter_name()
{
    local GAME
    GAME="$(doctor_adapter_normalize_game "${1:-}")"

    if doctor_adapter_exists "${GAME}"
    then
        echo "${GAME}"
    else
        echo "generic"
    fi
}


if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    case "${1:-}" in

        show)
            doctor_adapter_name "${2:-}"
        ;;

        *)
            echo "Uso:"
            echo "  adapters.sh show GAME"
            exit 1
        ;;

    esac
fi
