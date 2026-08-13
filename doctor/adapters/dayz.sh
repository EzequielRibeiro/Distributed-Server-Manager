#!/usr/bin/env bash

doctor_adapter_dayz_checks()
{
    local CONTEXT_JSON="$1"

    local SERVERFILES
    local EXECUTABLE
    local PROCESS_ENGINE

    SERVERFILES="$(
        jq -r '.paths.serverfiles' <<< "${CONTEXT_JSON}"
    )"

    EXECUTABLE="$(
        jq -r '.process.executable' <<< "${CONTEXT_JSON}"
    )"

    PROCESS_ENGINE="$(
        jq -r '.runtime.process_engine' <<< "${CONTEXT_JSON}"
    )"

    local FAILURES=0

    if [[ "${PROCESS_ENGINE}" == "native" ||
          "${PROCESS_ENGINE}" == "linuxgsm" ]]
    then
        echo "OK|Runtime|${PROCESS_ENGINE}"
    else
        echo "FAIL|Runtime|Runtime DayZ não reconhecido: ${PROCESS_ENGINE}"
        FAILURES=$((FAILURES + 1))
    fi

    if [[ -n "${EXECUTABLE}" ]]
    then
        local BINARY
        BINARY="${SERVERFILES}/${EXECUTABLE#./}"

        if [[ -f "${BINARY}" ]]
        then
            echo "OK|Executável|${BINARY}"
        else
            echo "FAIL|Executável|Não encontrado: ${BINARY}"
            FAILURES=$((FAILURES + 1))
        fi
    else
        echo "FAIL|Executável|EXECUTABLE não definido"
        FAILURES=$((FAILURES + 1))
    fi

    return "${FAILURES}"
}
