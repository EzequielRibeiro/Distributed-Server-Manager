#!/bin/bash
# =============================================================
# DSM Runtime Engine
#
# Responsável pelo armazenamento do estado Runtime
#
# Estrutura:
#
# runtime/state/<host>/<game>/<instance>/<module>.json
#
# =============================================================



DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

RUNTIME_DIR="${DSM_ROOT}/runtime"
STATE_DIR="${RUNTIME_DIR}/state"
RESOURCE_DIR="${RUNTIME_DIR}/resources"

mkdir -p "$STATE_DIR"
mkdir -p "$RESOURCE_DIR"

export DSM_ROOT
export RUNTIME_DIR
export STATE_DIR
export RESOURCE_DIR


# Contexto da execução
source "${DSM_ROOT}/core/runtime_context.sh"


# API Runtime
source "${DSM_ROOT}/core/lib/runtime.sh"



# =============================================================
# Atualizar recurso
# =============================================================

runtime_update_resource()
{
    local HOST="$1"
    local GAME="$2"
    local INSTANCE="$3"
    local MODULE="$4"
    local PATCH="$5"

    runtime_validate_resource "$HOST" "$GAME" "$INSTANCE"

    local RESOURCE_PATH
    RESOURCE_PATH="$(runtime_resource_path "$HOST" "$GAME" "$INSTANCE")"

    mkdir -p "$RESOURCE_PATH"

    local FILE="${RESOURCE_PATH}/${MODULE}.json"

    if [ ! -f "$FILE" ]; then
        echo "{}" > "$FILE"
    fi

    jq --argjson patch "$PATCH" '. * $patch' "$FILE" > "${FILE}.tmp"

    mv "${FILE}.tmp" "$FILE"
}


# =============================================================
# Obter recurso
# =============================================================

runtime_get_resource()
{

HOST="$1"
GAME="$2"
INSTANCE="$3"
MODULE="$4"



FILE="$STATE_DIR/$HOST/$GAME/$INSTANCE/$MODULE.json"



if [ -f "$FILE" ]
then

cat "$FILE"

else

echo "{}"

fi

}



# =============================================================
# Listar recursos
# =============================================================

runtime_list_resources()
{

find "$STATE_DIR" -name "*.json"

}



# =============================================================
# Remover recurso
# =============================================================

runtime_remove_resource()
{

HOST="$1"
GAME="$2"
INSTANCE="$3"
MODULE="$4"


FILE="$STATE_DIR/$HOST/$GAME/$INSTANCE/$MODULE.json"



if [ -f "$FILE" ]
then

rm "$FILE"

fi

}