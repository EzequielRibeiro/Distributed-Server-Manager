#!/bin/bash
# =============================================================
# mods/state.sh - MÓDULO 03 (MODS)
#
# Controle de estado dos Mods DSM
# DSM Mods state control
#
# Responsável por: | Responsible for:
# - registrar mods instalados | registering installed mods
# - controlar versão Workshop | controlling Workshop version
# - controlar pasta do mod | controlling mod folder
# - consultar estado | querying state
#
# Não executa: | DOES NOT execute:
# - SteamCMD
# - rsync
# - keys
# - rollback
#
# Fonte: | Source:
#   /opt/dsm/state/mods.state
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Arquivo de estado | State file
# =============================================================
STATE_DIR="${DSM_ROOT}/state"
STATE_FILE="${STATE_DIR}/mods.state"

mkdir -p "${STATE_DIR}"
touch "${STATE_FILE}"

# =============================================================
# Formato: | Format:
# WORKSHOP_ID|TIMESTAMP|FOLDER
# Exemplo: | Example:
# 1559212036|1723456789|@CF
# =============================================================

# =============================================================
# Obter timestamp | Get timestamp
#
# Uso: | Usage:
# state_get_timestamp ID
# =============================================================
state_get_timestamp()
{
    local id="$1"
    grep "^${id}|" "${STATE_FILE}" \
    | cut -d'|' -f2
}

# =============================================================
# Obter pasta | Get folder
#
# Uso: | Usage:
# state_get_folder ID
# =============================================================
state_get_folder()
{
    local id="$1"
    grep "^${id}|" "${STATE_FILE}" \
    | cut -d'|' -f3
}

# =============================================================
# Verificar existência | Check existence
#
# Uso: | Usage:
# state_exists ID
# =============================================================
state_exists()
{
    local id="$1"
    grep -q "^${id}|" "${STATE_FILE}"
}

# =============================================================
# Registrar estado | Set state
#
# Uso: | Usage:
# state_set ID TIMESTAMP FOLDER
# =============================================================
state_set()
{
    local id="$1"
    local timestamp="$2"
    local folder="$3"

    if [ -z "${id}" ] ||
       [ -z "${timestamp}" ] ||
       [ -z "${folder}" ]
    then
        log_error \
        "state_set parâmetros inválidos | invalid parameters"
        return 1
    fi

    # Remove registro antigo | Remove old record
    state_remove "${id}"

    # Adiciona novo estado | Add new state
    echo \
    "${id}|${timestamp}|${folder}" \
    >> "${STATE_FILE}"

    log_ok \
    "Estado atualizado | State updated: ${folder}"
}

# =============================================================
# Remover estado | Remove state
#
# Uso: | Usage:
# state_remove ID
# =============================================================
state_remove()
{
    local id="$1"
    if [ -z "${id}" ]
    then
        return 1
    fi

    if [ -f "${STATE_FILE}" ]
    then
        grep -v "^${id}|" \
        "${STATE_FILE}" \
        > "${STATE_FILE}.tmp"

        mv \
        "${STATE_FILE}.tmp" \
        "${STATE_FILE}"
    fi
}

# =============================================================
# Listar estado | List state
#
# Uso: | Usage:
# state_list
# =============================================================
state_list()
{
    if [ ! -s "${STATE_FILE}" ]
    then
        echo
        echo "Nenhum mod registrado | No mods registered."
        return 0
    fi

    echo
    echo "Mods DSM"
    echo "------------------------------------"

    while IFS='|' read -r id timestamp folder
    do
        printf "%-15s %-20s %s\n" \
        "${id}" \
        "${timestamp}" \
        "${folder}"
    done < "${STATE_FILE}"
}

state_sync_from_workshop()
{
    local mods_dir="${SERVERFILES_PATH}/mods"
    if [ ! -d "${mods_dir}" ]
    then
        log_error "Diretório de mods não encontrado | Mods directory not found."
        return 1
    fi

    while IFS= read -r meta
    do
        local folder
        local id
        folder=$(basename "$(dirname "${meta}")")
        id=$(
            grep -Eo \
            'publishedid[[:space:]]*=[[:space:]]*[0-9]+' \
            "${meta}" \
            | grep -Eo '[0-9]+'
        )
        if [ -n "${id}" ] &&
           [ -n "${folder}" ]
        then
            state_set \
            "${id}" \
            "$(date +%s)" \
            "${folder}"
        fi
    done < <(
        find -L "${mods_dir}" \
        -mindepth 2 \
        -maxdepth 2 \
        -name meta.cpp
    )
}

# =============================================================
# Limpar estado | Clear state
#
# Uso: | Usage:
# state_clear
# =============================================================
state_clear()
{
    > "${STATE_FILE}"
    log_ok \
    "Estado de Mods limpo | Mods state cleared."
}

# =============================================================
# Exportação | Export
# =============================================================
export -f state_get_timestamp
export -f state_get_folder
export -f state_exists
export -f state_set
export -f state_remove
export -f state_list
export -f state_clear
export -f state_sync_from_workshop
