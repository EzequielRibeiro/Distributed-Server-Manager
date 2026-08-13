#!/bin/bash
#
# DSM Runtime Library
# Version: 1.0.0
#
# Funções comuns para gerenciamento do estado compartilhado DSM
# Common functions for DSM shared state management
#

RUNTIME_DIR="/opt/dsm/runtime"
STATE_DIR="${RUNTIME_DIR}/state"
LOCK_DIR="${RUNTIME_DIR}/locks"
HISTORY_DIR="${RUNTIME_DIR}/history"


#
# Inicializa estrutura Runtime
# Initialize Runtime structure
#
runtime_init()
{
    mkdir -p "$STATE_DIR"
    mkdir -p "$LOCK_DIR"
    mkdir -p "$HISTORY_DIR"
}


#
# Verifica se módulo possui estado
# Checks if module has state
#
runtime_exists()
{
    local module="$1"

    if [ -f "${STATE_DIR}/${module}.json" ]; then
        return 0
    fi

    return 1
}


#
# Lê estado de um módulo
# Reads module state
#
# Exemplo: | Example:
# runtime_get server
#
runtime_get()
{
    local module="$1"
    local file="${STATE_DIR}/${module}.json"

    if [ -f "$file" ]; then
        cat "$file"
    else
        echo "{}"
    fi
}

#
# Normaliza tipos de dados em um JSON
# Normalizes data types in a JSON
#
runtime_normalize_json()
{
    local json="$1"

    jq '
    walk(
        if type == "string" then

            if test("^-?[0-9]+$") then
                tonumber

            elif test("^-?[0-9]+\\.[0-9]+$") then
                tonumber

            elif . == "true" then
                true

            elif . == "false" then
                false

            elif . == "null" then
                null

            else
                .
            end

        else
            .
        end
    )
    ' <<< "${json}"
}

#
# Cria ou substitui estado
# Creates or replaces state
#
# Exemplo: | Example:
# runtime_set server '{"status":"online"}'
#
runtime_set()
{
  local module="$1"
  local data="$2"
  local file="${STATE_DIR}/${module}.json"
  data=$(runtime_normalize_json "${data}")
  echo "${data}" > "${file}"
}


#
# Atualiza campo simples no JSON
# Updates simple field in JSON
#
# Requer jq | Requires jq
#
# Exemplo: | Example:
# runtime_update server status online
#
runtime_update()
{
    local module="$1"
    local key="$2"
    local value="$3"

    local file="${STATE_DIR}/${module}.json"


    if [ ! -f "$file" ]; then
        echo "{}" > "$file"
    fi


    # Detecta tipo JSON automaticamente
    # Automatically detects JSON type
    if [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]]; then

        jq \
        --argjson value "$value" \
        ".${key}=\$value" \
        "$file" > "${file}.tmp"


    elif [[ "$value" == "true" || "$value" == "false" ]]; then

        jq \
        --argjson value "$value" \
        ".${key}=\$value" \
        "$file" > "${file}.tmp"


    elif [[ "$value" == "null" ]]; then

        jq \
        ".${key}=null" \
        "$file" > "${file}.tmp"


    else

        jq \
        --arg value "$value" \
        ".${key}=\$value" \
        "$file" > "${file}.tmp"

    fi


    mv "${file}.tmp" "$file"
}


#
# Retorna timestamp padrão DSM
# Returns default DSM timestamp
#
runtime_timestamp()
{
    date +"%Y-%m-%dT%H:%M:%S"
}


#
# Cria lock de módulo
# Creates module lock
#
runtime_lock()
{
    local module="$1"

    mkdir "${LOCK_DIR}/${module}.lock" 2>/dev/null
}


#
# Remove lock
# Removes lock
#
runtime_unlock()
{
    local module="$1"

    rmdir "${LOCK_DIR}/${module}.lock" 2>/dev/null
}


#
# Verifica saúde do Runtime
# Checks Runtime health
#
runtime_health()
{
    local count

    count=$(ls "${STATE_DIR}"/*.json 2>/dev/null | wc -l)


    if [ "$count" -gt 0 ]; then
        echo "Runtime HEALTHY"
    else
        echo "Runtime EMPTY"
    fi
}
