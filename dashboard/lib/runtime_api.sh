#!/usr/bin/env bash

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

RUNTIME_STATE="${DSM_ROOT}/runtime/state"


runtime_read()
{
    local MODULE="$1"

    local FILE="${RUNTIME_STATE}/${MODULE}.json"


    if [[ -f "$FILE" ]]
    then
        cat "$FILE"
    else
        echo "{}"
    fi
}