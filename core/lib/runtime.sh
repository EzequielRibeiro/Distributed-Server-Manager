#!/usr/bin/env bash
# =============================================================
# DSM Runtime Library
#
# Responsável:
#   - Estado compartilhado DSM
#   - Comunicação entre módulos
#   - Runtime multi recurso
#
# Modelo:
#
#   runtime/state/
#        módulos globais
#
#   runtime/resources/
#        SERVER/GAME/INSTANCE
#
# Exemplo:
#
#   runtime/resources/
#       server01/
#           dayz/
#               survival01/
#                   server.json
#
# =============================================================


set -Eeuo pipefail


export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


RUNTIME_DIR="${DSM_ROOT}/runtime"

STATE_DIR="${RUNTIME_DIR}/state"

RESOURCE_DIR="${RUNTIME_DIR}/resources"

LOCK_DIR="${RUNTIME_DIR}/locks"

HISTORY_DIR="${RUNTIME_DIR}/history"



# =============================================================
# Inicialização
# =============================================================

runtime_init()
{

    STATE_DIR="${DSM_ROOT}/runtime/state"
    LOCK_DIR="${DSM_ROOT}/runtime/lock"
    HISTORY_DIR="${DSM_ROOT}/runtime/history"
    RESOURCE_DIR="${DSM_ROOT}/runtime/state"


    export STATE_DIR
    export LOCK_DIR
    export HISTORY_DIR
    export RESOURCE_DIR


    mkdir -p \
        "${STATE_DIR}" \
        "${LOCK_DIR}" \
        "${HISTORY_DIR}" \
        "${RESOURCE_DIR}"

}



# =============================================================
# Normalização JSON
# =============================================================

# shellcheck disable=SC2120
runtime_normalize_json()
{

    local JSON


    if [ "$#" -gt 0 ]
    then

        JSON="$1"

    else

        JSON="$(cat)"

    fi



    echo "$JSON" \
    | jq '
    walk(
        if type == "string" then

            if test("^-?[0-9]+$") then
                tonumber

            elif test("^-?[0-9]+\\.[0-9]+$") then
                tonumber

            elif . == "true" then
                true

            elif . == "false" then
                true

            elif . == "null" then
                null

            else
                .
            end

        else
            .
        end
    )
    '

}


# =============================================================
# Runtime Global SET
#
# runtime_set server "{}"
#
# =============================================================

runtime_set()
{

    local MODULE="$1"
    local DATA="$2"


    local FILE

    FILE="${STATE_DIR}/${MODULE}.json"



    echo "$DATA" \
    | runtime_normalize_json \
    > "$FILE"

}



# =============================================================
# Runtime Global GET
#
# =============================================================

runtime_get()
{

    local MODULE="$1"


    local FILE

    FILE="${STATE_DIR}/${MODULE}.json"



    if [ -f "$FILE" ]
    then

        cat "$FILE"

    else

        echo "{}"

    fi

}



# =============================================================
# Runtime Global UPDATE
#
# Merge parcial
#
# =============================================================

runtime_update()
{

    local MODULE="$1"

    local PATCH="$2"


    local FILE

    FILE="${STATE_DIR}/${MODULE}.json"



    if [ ! -f "$FILE" ]
    then

        echo "{}" > "$FILE"

    fi



    jq \
    --argjson patch "$PATCH" \
    '. * $patch' \
    "$FILE" \
    > "${FILE}.tmp"



    mv "${FILE}.tmp" "$FILE"

}



# =============================================================
# Resource Validation
#
# SERVER/GAME/INSTANCE
#
# =============================================================

runtime_validate_resource()
{

    local HOST="$1"
    local GAME="$2"
    local INSTANCE="$3"



    if [[ -z "$HOST" ||
          -z "$GAME" ||
          -z "$INSTANCE" ]]
    then

        return 1

    fi


    return 0

}



# =============================================================
# Resource Identity Path
#
# SERVER/GAME/INSTANCE
#
# =============================================================

runtime_resource_path()
{

    local HOST="$1"
    local GAME="$2"
    local INSTANCE="$3"


    echo "${RESOURCE_DIR}/${HOST}/${GAME}/${INSTANCE}"

}



# =============================================================
# Runtime Resource SET
#
# Substitui módulo completo
#
# Exemplo:
#
# runtime_set_resource \
# server01 dayz survival01 server "{}"
#
# =============================================================

runtime_set_resource()
{

    local HOST="$1"
    local GAME="$2"
    local INSTANCE="$3"
    local MODULE="$4"
    local DATA="$5"



    runtime_validate_resource \
    "$HOST" \
    "$GAME" \
    "$INSTANCE"



    local RESOURCE_PATH


    RESOURCE_PATH="$(runtime_resource_path \
    "$HOST" \
    "$GAME" \
    "$INSTANCE")"



    mkdir -p "$RESOURCE_PATH"



    echo "$DATA" \
    | runtime_normalize_json \
    > "${RESOURCE_PATH}/${MODULE}.json"

}



# =============================================================
# Runtime Resource GET
#
# =============================================================

runtime_get_resource()
{

    local HOST="$1"
    local GAME="$2"
    local INSTANCE="$3"
    local MODULE="$4"



    runtime_validate_resource \
    "$HOST" \
    "$GAME" \
    "$INSTANCE"



    local FILE


    FILE="$(runtime_resource_path \
    "$HOST" \
    "$GAME" \
    "$INSTANCE")/${MODULE}.json"



    if [ -f "$FILE" ]
    then

        cat "$FILE"

    else

        echo "{}"

    fi

}



# =============================================================
# Runtime Resource UPDATE
#
# Merge parcial
#
# =============================================================

runtime_update_resource()
{

    local HOST="$1"
    local GAME="$2"
    local INSTANCE="$3"
    local MODULE="$4"
    local PATCH="$5"



    runtime_validate_resource \
    "$HOST" \
    "$GAME" \
    "$INSTANCE"



    local RESOURCE_PATH

    local FILE



    RESOURCE_PATH="$(runtime_resource_path \
    "$HOST" \
    "$GAME" \
    "$INSTANCE")"



    mkdir -p "$RESOURCE_PATH"



    FILE="${RESOURCE_PATH}/${MODULE}.json"



    if [ ! -f "$FILE" ]
    then

        echo "{}" > "$FILE"

    fi



    jq \
    --argjson patch "$PATCH" \
    '. * $patch' \
    "$FILE" \
    > "${FILE}.tmp"



    mv "${FILE}.tmp" "$FILE"

}



# =============================================================
# Lista Recursos
# =============================================================

runtime_list_resources()
{

    find "$RESOURCE_DIR" \
    -type f \
    -name "*.json" \
    2>/dev/null \
    | sed \
    "s#$RESOURCE_DIR/##" \
    | sed \
    's#/# #g;s/.json//'

}



# =============================================================
# Health Runtime
# =============================================================

runtime_health()
{

    if [ -d "$RUNTIME_DIR" ]
    then

        echo "OK"

    else

        echo "ERROR"

    fi

}


