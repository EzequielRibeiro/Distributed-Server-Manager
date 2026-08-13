#!/usr/bin/env bash

doctor_adapter_generic_checks()
{
    local CONTEXT_JSON="$1"

    local INSTANCE_PATH
    local SERVERFILES

    INSTANCE_PATH="$(
        jq -r '.path' <<< "${CONTEXT_JSON}"
    )"

    SERVERFILES="$(
        jq -r '.paths.serverfiles' <<< "${CONTEXT_JSON}"
    )"

    local FAILURES=0

    if [[ -d "${INSTANCE_PATH}" ]]
    then
        echo "OK|Estrutura|Diretório da instância presente"
    else
        echo "FAIL|Estrutura|Diretório da instância ausente"
        FAILURES=$((FAILURES + 1))
    fi

    if [[ -f "${INSTANCE_PATH}/instance.conf" ]]
    then
        echo "OK|Configuração|instance.conf presente"
    else
        echo "FAIL|Configuração|instance.conf ausente"
        FAILURES=$((FAILURES + 1))
    fi

    if [[ -d "${SERVERFILES}" ]]
    then
        echo "OK|Serverfiles|${SERVERFILES}"
    else
        echo "FAIL|Serverfiles|Diretório ausente: ${SERVERFILES}"
        FAILURES=$((FAILURES + 1))
    fi

    local FREE_PCT

    FREE_PCT="$(
        df -P "${INSTANCE_PATH}" 2>/dev/null |
        awk '
            NR == 2 {
                gsub("%", "", $5)
                print 100 - $5
            }
        '
    )"

    if [[ -n "${FREE_PCT}" ]]
    then
        if (( FREE_PCT >= 15 ))
        then
            echo "OK|Disco|${FREE_PCT}% livre"
        else
            echo "FAIL|Disco|Somente ${FREE_PCT}% livre"
            FAILURES=$((FAILURES + 1))
        fi
    else
        echo "FAIL|Disco|Não foi possível consultar espaço livre"
        FAILURES=$((FAILURES + 1))
    fi

    return "${FAILURES}"
}
