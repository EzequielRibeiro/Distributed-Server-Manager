#!/usr/bin/env bash

doctor_adapter_minecraft_checks()
{
    local CONTEXT_JSON="$1"

    local SERVERFILES
    local JAVA_BIN
    local EXECUTABLE
    local PROCESS_ENGINE

    SERVERFILES="$(
        jq -r '.paths.serverfiles' <<< "${CONTEXT_JSON}"
    )"

    JAVA_BIN="$(
        jq -r '.process.java_bin' <<< "${CONTEXT_JSON}"
    )"

    EXECUTABLE="$(
        jq -r '.process.executable' <<< "${CONTEXT_JSON}"
    )"

    PROCESS_ENGINE="$(
        jq -r '.runtime.process_engine' <<< "${CONTEXT_JSON}"
    )"

    local FAILURES=0

    if [[ "${PROCESS_ENGINE}" == "java" ]]
    then
        echo "OK|Runtime|Process engine Java"
    else
        echo "FAIL|Runtime|Process engine esperado: java"
        FAILURES=$((FAILURES + 1))
    fi

    if [[ -n "${JAVA_BIN}" && -x "${JAVA_BIN}" ]]
    then
        echo "OK|Java|${JAVA_BIN}"
    else
        echo "FAIL|Java|JAVA_BIN ausente ou não executável"
        FAILURES=$((FAILURES + 1))
    fi

    if [[ -n "${EXECUTABLE}" &&
          -f "${SERVERFILES}/${EXECUTABLE}" ]]
    then
        echo "OK|Executável|${SERVERFILES}/${EXECUTABLE}"
    else
        echo "FAIL|Executável|server.jar não encontrado"
        FAILURES=$((FAILURES + 1))
    fi

    return "${FAILURES}"
}
