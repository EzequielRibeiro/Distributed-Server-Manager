#!/usr/bin/env bash

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

INSTANCES_SCRIPT="${DSM_ROOT}/doctor/instances.sh"
CONTEXT_SCRIPT="${DSM_ROOT}/doctor/instance_context.sh"
ADAPTER_REGISTRY="${DSM_ROOT}/doctor/adapters.sh"

doctor_instance_runner()
{
    local DISCOVERY
    DISCOVERY="$(
        bash "${INSTANCES_SCRIPT}" json
    )" || return 1

    local TOTAL=0
    local READY=0
    local WARNING=0
    local INCOMPLETE=0
    local PENDING=0
    local PROVISIONING=0
    local PROVISION_FAILED=0

    while IFS= read -r INSTANCE_JSON
    do
        TOTAL=$((TOTAL + 1))

        local PATH_VALUE
        local GAME
        local INSTANCE
        local STRUCTURE_STATUS

        PATH_VALUE="$(
            jq -r '.path' <<< "${INSTANCE_JSON}"
        )"

        GAME="$(
            jq -r '.game' <<< "${INSTANCE_JSON}"
        )"

        INSTANCE="$(
            jq -r '.instance' <<< "${INSTANCE_JSON}"
        )"

        STRUCTURE_STATUS="$(
            jq -r '.structure_status' <<< "${INSTANCE_JSON}"
        )"

        echo
        echo "============================================================"
        echo "Instância : ${INSTANCE}"
        echo "Jogo      : ${GAME}"
        echo "Caminho   : ${PATH_VALUE}"
        echo "============================================================"

        if [[ "${STRUCTURE_STATUS}" != "ready" ]]
        then
            case "${STRUCTURE_STATUS}" in

                pending_steam_auth)
                    local PROGRESS
                    local MESSAGE

                    PROGRESS="$(
                        jq -r '.provision.progress // 0'                             <<< "${INSTANCE_JSON}"
                    )"

                    MESSAGE="$(
                        jq -r '.provision.message // ""'                             <<< "${INSTANCE_JSON}"
                    )"

                    echo                     "PENDING|Steam Auth|${MESSAGE} (${PROGRESS}%)"

                    PENDING=$((PENDING + 1))

                    continue
                ;;

                pending_install)
                    local PROGRESS
                    local MESSAGE

                    PROGRESS="$(
                        jq -r '.provision.progress // 0'                             <<< "${INSTANCE_JSON}"
                    )"

                    MESSAGE="$(
                        jq -r '.provision.message // ""'                             <<< "${INSTANCE_JSON}"
                    )"

                    echo                     "PENDING|Instalação|${MESSAGE} (${PROGRESS}%)"

                    PENDING=$((PENDING + 1))

                    continue
                ;;

                provisioning)
                    local PROGRESS
                    local STAGE
                    local MESSAGE

                    PROGRESS="$(
                        jq -r '.provision.progress // 0'                             <<< "${INSTANCE_JSON}"
                    )"

                    STAGE="$(
                        jq -r '.provision.stage // ""'                             <<< "${INSTANCE_JSON}"
                    )"

                    MESSAGE="$(
                        jq -r '.provision.message // ""'                             <<< "${INSTANCE_JSON}"
                    )"

                    echo                     "PROVISIONING|${STAGE}|${MESSAGE} (${PROGRESS}%)"

                    PROVISIONING=$((PROVISIONING + 1))

                    continue
                ;;

                provision_failed)
                    local MESSAGE

                    MESSAGE="$(
                        jq -r '.provision.message // ""'                             <<< "${INSTANCE_JSON}"
                    )"

                    echo                     "FAIL|Provisionamento|${MESSAGE}"

                    PROVISION_FAILED=$((PROVISION_FAILED + 1))
                    WARNING=$((WARNING + 1))

                    continue
                ;;

                incomplete)
                    echo                     "INCOMPLETE|Estrutura|Instância não possui estrutura completa"

                    INCOMPLETE=$((INCOMPLETE + 1))

                    continue
                ;;

                *)
                    echo                     "FAIL|Estado|Estado desconhecido: ${STRUCTURE_STATUS}"

                    WARNING=$((WARNING + 1))

                    continue
                ;;

            esac
        fi

        local CONTEXT
        if ! CONTEXT="$(
            bash "${CONTEXT_SCRIPT}" show "${PATH_VALUE}"
        )"
        then
            echo "FAIL|Contexto|Falha ao carregar contexto da instância"
            WARNING=$((WARNING + 1))
            continue
        fi

        local GAME_NORMALIZED
        GAME_NORMALIZED="${GAME,,}"

        local RC_GENERIC=0
        local RC_GAME=0

        local RC=0

        if (
            export DSM_ROOT

            source "${ADAPTER_REGISTRY}"

            doctor_adapter_load "${GAME_NORMALIZED}"

            echo
            echo "--- GENERIC ---"

            if doctor_adapter_generic_checks "${CONTEXT}"
            then
                RC_GENERIC=0
            else
                RC_GENERIC=$?
            fi

            echo
            echo "--- ${GAME_NORMALIZED^^} ---"

            local FUNC="doctor_adapter_${GAME_NORMALIZED}_checks"

            if declare -F "${FUNC}" >/dev/null
            then
                if "${FUNC}" "${CONTEXT}"
                then
                    RC_GAME=0
                else
                    RC_GAME=$?
                fi
            else
                echo "INFO|Adapter|Sem adapter específico; somente checks genéricos"
                RC_GAME=0
            fi

            if (( RC_GENERIC == 0 && RC_GAME == 0 ))
            then
                exit 0
            fi

            exit 1
        )
        then
            RC=0
        else
            RC=$?
        fi

        if (( RC == 0 ))
        then
            echo
            echo "RESULTADO|OK|Instância saudável"
            READY=$((READY + 1))
        else
            echo
            echo "RESULTADO|WARNING|Instância possui falhas"
            WARNING=$((WARNING + 1))
        fi

    done < <(
        jq -c '.instances[]' <<< "${DISCOVERY}"
    )

    echo
    echo "============================================================"
    echo "RESUMO DO DOCTOR"
    echo "============================================================"
    echo "Total             : ${TOTAL}"
    echo "OK                : ${READY}"
    echo "Pending           : ${PENDING}"
    echo "Provisioning      : ${PROVISIONING}"
    echo "Provision Failed  : ${PROVISION_FAILED}"
    echo "Warning           : ${WARNING}"
    echo "Incomplete        : ${INCOMPLETE}"

    if (( WARNING > 0 ))
    then
        return 1
    fi

    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    doctor_instance_runner
fi
