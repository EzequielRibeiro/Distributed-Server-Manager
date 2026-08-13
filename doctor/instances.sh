#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Doctor - Instance Discovery
#
# Responsável:
#   Descobrir instâncias válidas na estrutura:
#
#   INSTANCE_ROOT / NODE / GAME / INSTANCE
#
# Este módulo:
#   - NÃO inicia instâncias
#   - NÃO para instâncias
#   - NÃO reinicia instâncias
#   - NÃO altera configurações
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
INSTANCE_ROOT="${INSTANCE_ROOT:-${DSM_ROOT}/instances}"


# =============================================================
# Caminho relativo
# =============================================================

doctor_instance_relative_path()
{
    local INSTANCE_PATH="$1"

    printf '%s\n' \
        "${INSTANCE_PATH#${INSTANCE_ROOT}/}"
}


# =============================================================
# Extrair identidade pelo caminho
#
# Estrutura esperada:
#
# NODE / GAME / INSTANCE
#
# =============================================================

doctor_instance_identity()
{
    local INSTANCE_PATH="$1"

    local RELATIVE

    RELATIVE="$(
        doctor_instance_relative_path \
            "${INSTANCE_PATH}"
    )"

    local NODE
    local GAME
    local INSTANCE

    IFS='/' read -r \
        NODE \
        GAME \
        INSTANCE \
        EXTRA \
        <<< "${RELATIVE}"

    if [[ -z "${NODE:-}" ]] ||
       [[ -z "${GAME:-}" ]] ||
       [[ -z "${INSTANCE:-}" ]] ||
       [[ -n "${EXTRA:-}" ]]
    then
        return 1
    fi

    printf '%s|%s|%s\n' \
        "${NODE}" \
        "${GAME}" \
        "${INSTANCE}"
}


# =============================================================
# Instance.conf
# =============================================================

doctor_instance_config()
{
    local INSTANCE_PATH="$1"

    printf '%s/instance.conf\n' \
        "${INSTANCE_PATH}"
}


# =============================================================
# Metadata
# =============================================================

doctor_instance_metadata()
{
    local INSTANCE_PATH="$1"

    printf '%s/.dsm/instance-metadata.json\n' \
        "${INSTANCE_PATH}"
}


# =============================================================
# Possui estrutura básica?
# =============================================================

doctor_instance_has_structure()
{
    local INSTANCE_PATH="$1"

    doctor_instance_identity \
        "${INSTANCE_PATH}" \
        >/dev/null
}


# =============================================================
# Possui instance.conf?
# =============================================================

doctor_instance_has_config()
{
    local INSTANCE_PATH="$1"

    [[ -f "$(doctor_instance_config "${INSTANCE_PATH}")" ]]
}


# =============================================================
# Possui metadata?
# =============================================================

doctor_instance_has_metadata()
{
    local INSTANCE_PATH="$1"

    local FILE

    FILE="$(
        doctor_instance_metadata \
            "${INSTANCE_PATH}"
    )"

    [[ -f "${FILE}" ]] &&
    jq -e '
        type == "object"
    ' "${FILE}" >/dev/null 2>&1
}


# =============================================================
# Provision resource
# =============================================================

doctor_instance_provision()
{
    local INSTANCE_PATH="$1"

    local IDENTITY

    IDENTITY="$(
        doctor_instance_identity "${INSTANCE_PATH}" 2>/dev/null
    )" || return 1

    local NODE
    local GAME
    local INSTANCE

    IFS='|' read -r \
        NODE \
        GAME \
        INSTANCE \
        <<< "${IDENTITY}"

    printf '%s/runtime/resources/%s/%s/%s/provision.json\n' \
        "${DSM_ROOT}" \
        "${NODE}" \
        "${GAME}" \
        "${INSTANCE}"
}


doctor_instance_has_provision()
{
    local INSTANCE_PATH="$1"

    local FILE

    FILE="$(
        doctor_instance_provision "${INSTANCE_PATH}"
    )" || return 1

    [[ -f "${FILE}" ]] &&
    jq -e '
        type == "object" and
        (.status | type == "string")
    ' "${FILE}" >/dev/null 2>&1
}


doctor_instance_provision_status()
{
    local INSTANCE_PATH="$1"

    local FILE

    FILE="$(
        doctor_instance_provision "${INSTANCE_PATH}"
    )" || {
        echo ""
        return 1
    }

    if [[ ! -f "${FILE}" ]]
    then
        echo ""
        return 0
    fi

    jq -r '.status // ""' "${FILE}" 2>/dev/null
}


doctor_instance_provision_stage()
{
    local INSTANCE_PATH="$1"

    local FILE

    FILE="$(
        doctor_instance_provision "${INSTANCE_PATH}"
    )" || {
        echo ""
        return 1
    }

    if [[ ! -f "${FILE}" ]]
    then
        echo ""
        return 0
    fi

    jq -r '.stage // ""' "${FILE}" 2>/dev/null
}


doctor_instance_provision_progress()
{
    local INSTANCE_PATH="$1"

    local FILE

    FILE="$(
        doctor_instance_provision "${INSTANCE_PATH}"
    )" || {
        echo "0"
        return 1
    }

    if [[ ! -f "${FILE}" ]]
    then
        echo "0"
        return 0
    fi

    jq -r '.progress // 0' "${FILE}" 2>/dev/null
}


doctor_instance_provision_message()
{
    local INSTANCE_PATH="$1"

    local FILE

    FILE="$(
        doctor_instance_provision "${INSTANCE_PATH}"
    )" || {
        echo ""
        return 1
    }

    if [[ ! -f "${FILE}" ]]
    then
        echo ""
        return 0
    fi

    jq -r '.message // ""' "${FILE}" 2>/dev/null
}


# =============================================================
# Status estrutural
#
# ready
# incomplete
#
# =============================================================

doctor_instance_structure_status()
{
    local INSTANCE_PATH="$1"

    if ! doctor_instance_has_structure "${INSTANCE_PATH}"
    then
        echo "invalid"
        return 1
    fi

    #
    # Instância completamente materializada.
    #
    if doctor_instance_has_config "${INSTANCE_PATH}"
    then
        echo "ready"
        return 0
    fi

    #
    # Sem instance.conf, verificar se existe um fluxo legítimo
    # de provisionamento.
    #
    if doctor_instance_has_metadata "${INSTANCE_PATH}" &&
       doctor_instance_has_provision "${INSTANCE_PATH}"
    then
        local PROVISION_STATUS

        PROVISION_STATUS="$(
            doctor_instance_provision_status "${INSTANCE_PATH}"
        )"

        case "${PROVISION_STATUS}" in

            pending_steam_auth)
                echo "pending_steam_auth"
                return 0
            ;;

            queued|pending|provisioning|installing|running)
                echo "provisioning"
                return 0
            ;;

            failed|error)
                echo "provision_failed"
                return 0
            ;;

            offline|completed|ready)
                #
                # Provisionamento diz concluído, mas instance.conf
                # não existe. Isto sim é inconsistência estrutural.
                #
                echo "incomplete"
                return 0
            ;;

            *)
                echo "pending_install"
                return 0
            ;;

        esac
    fi

    #
    # Sem configuração e sem estado legítimo de provisionamento.
    #
    echo "incomplete"
    return 0
}

# =============================================================
# Descobrir diretórios candidatos
#
# Apenas profundidade:
#
# NODE / GAME / INSTANCE
#
# =============================================================

doctor_instances_find()
{
    [[ -d "${INSTANCE_ROOT}" ]] ||
        return 0

    find "${INSTANCE_ROOT}" \
        -mindepth 3 \
        -maxdepth 3 \
        -type d \
        -print \
        2>/dev/null |
        sort
}


# =============================================================
# Listagem estruturada
# =============================================================

doctor_instances_list()
{
    local INSTANCE_PATH

    while IFS= read -r INSTANCE_PATH
    do
        [[ -n "${INSTANCE_PATH}" ]] ||
            continue

        local IDENTITY

        IDENTITY="$(
            doctor_instance_identity \
                "${INSTANCE_PATH}" \
                2>/dev/null
        )" || continue

        local NODE
        local GAME
        local INSTANCE

        IFS='|' read -r \
            NODE \
            GAME \
            INSTANCE \
            <<< "${IDENTITY}"

        local STATUS
        local HAS_CONFIG=false
        local HAS_METADATA=false
        local HAS_PROVISION=false

        local PROVISION_STATUS=""
        local PROVISION_STAGE=""
        local PROVISION_PROGRESS=0
        local PROVISION_MESSAGE=""

        STATUS="$(
            doctor_instance_structure_status \
                "${INSTANCE_PATH}"
        )"

        if doctor_instance_has_config "${INSTANCE_PATH}"
        then
            HAS_CONFIG=true
        fi

        if doctor_instance_has_metadata "${INSTANCE_PATH}"
        then
            HAS_METADATA=true
        fi

        if doctor_instance_has_provision "${INSTANCE_PATH}"
        then
            HAS_PROVISION=true

            PROVISION_STATUS="$(
                doctor_instance_provision_status \
                    "${INSTANCE_PATH}"
            )"

            PROVISION_STAGE="$(
                doctor_instance_provision_stage \
                    "${INSTANCE_PATH}"
            )"

            PROVISION_PROGRESS="$(
                doctor_instance_provision_progress \
                    "${INSTANCE_PATH}"
            )"

            PROVISION_MESSAGE="$(
                doctor_instance_provision_message \
                    "${INSTANCE_PATH}"
            )"
        fi

        jq -nc \
            --arg node "${NODE}" \
            --arg game "${GAME}" \
            --arg instance "${INSTANCE}" \
            --arg path "${INSTANCE_PATH}" \
            --arg status "${STATUS}" \
            --argjson has_config "${HAS_CONFIG}" \
            --argjson has_metadata "${HAS_METADATA}" \
            --argjson has_provision "${HAS_PROVISION}" \
            --arg provision_status "${PROVISION_STATUS}" \
            --arg provision_stage "${PROVISION_STAGE}" \
            --argjson provision_progress "${PROVISION_PROGRESS:-0}" \
            --arg provision_message "${PROVISION_MESSAGE}" \
            '{
                node: $node,
                game: $game,
                instance: $instance,
                path: $path,
                structure_status: $status,
                has_instance_config: $has_config,
                has_metadata: $has_metadata,
                has_provision: $has_provision,
                provision: {
                    status: $provision_status,
                    stage: $provision_stage,
                    progress: $provision_progress,
                    message: $provision_message
                }
            }'

    done < <(
        doctor_instances_find
    )
}

# =============================================================
# JSON completo
# =============================================================

doctor_instances_json()
{
    doctor_instances_list |
        jq -s '{
            instances: .,

            total: length,

            ready:
                [
                    .[]
                    | select(.structure_status == "ready")
                ] | length,

            pending_steam_auth:
                [
                    .[]
                    | select(.structure_status == "pending_steam_auth")
                ] | length,

            provisioning:
                [
                    .[]
                    | select(.structure_status == "provisioning")
                ] | length,

            pending_install:
                [
                    .[]
                    | select(.structure_status == "pending_install")
                ] | length,

            provision_failed:
                [
                    .[]
                    | select(.structure_status == "provision_failed")
                ] | length,

            incomplete:
                [
                    .[]
                    | select(.structure_status == "incomplete")
                ] | length
        }'
}

# =============================================================
# Export
# =============================================================

export -f doctor_instance_relative_path
export -f doctor_instance_identity
export -f doctor_instance_config
export -f doctor_instance_metadata
export -f doctor_instance_has_structure
export -f doctor_instance_has_config
export -f doctor_instance_has_metadata
export -f doctor_instance_provision
export -f doctor_instance_has_provision
export -f doctor_instance_provision_status
export -f doctor_instance_provision_stage
export -f doctor_instance_provision_progress
export -f doctor_instance_provision_message
export -f doctor_instance_structure_status
export -f doctor_instances_find
export -f doctor_instances_list
export -f doctor_instances_json


# =============================================================
# CLI
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    case "${1:-json}" in

        list)
            doctor_instances_list
        ;;

        json)
            doctor_instances_json
        ;;

        *)
            echo "Uso:"
            echo "  instances.sh list"
            echo "  instances.sh json"
            exit 1
        ;;

    esac

fi