#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Runtime Context Resolver
#
# Responsável:
#
# - resolver node
# - resolver game
# - resolver instance
# - resolver paths
#
# Fonte única:
#
# agent.conf + ambiente runtime
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# =============================================================
# Carrega Runtime Global
# =============================================================

if [[ -f "${DSM_ROOT}/config/runtime.sh" ]]
then
    source "${DSM_ROOT}/config/runtime.sh"
fi


# =============================================================
# Defaults do Agent
# =============================================================

INSTANCE_ROOT="${INSTANCE_ROOT:-${DSM_ROOT}/instances}"

export INSTANCE_ROOT


# =============================================================
# Validação
# =============================================================

runtime_validate()
{

    if [[ -z "${DSM_NODE_ID:-}" ]]
    then
        echo "DSM_NODE_ID não definido"
        return 1
    fi


    if [[ -z "${INSTANCE_ROOT:-}" ]]
    then
        echo "INSTANCE_ROOT não definido"
        return 1
    fi

}

runtime_launcher()
{
    get_instance_launcher
}

# =============================================================
# Identidade
# =============================================================

runtime_game()
{

    if [[ -z "${GAME_ID:-}" ]]
    then
        echo "GAME_ID não definido" >&2
        return 1
    fi


    echo "${GAME_ID}"

}


runtime_instance()
{
    echo "${DSM_INSTANCE_ID:-}"
}


runtime_node()
{
    echo "${DSM_NODE_ID:-}"
}


runtime_host()
{
    echo "${DSM_NODE_ID:-}"
}


# =============================================================
# Caminho da instância
# =============================================================

get_instance_path()
{

    runtime_validate


    if [[ -z "${GAME_ID:-}" ]]
    then
        echo "GAME_ID não definido" >&2
        return 1
    fi


    if [[ -z "${DSM_INSTANCE_ID:-}" ]]
    then
        echo "DSM_INSTANCE_ID não definido" >&2
        return 1
    fi


    echo "${INSTANCE_ROOT}/${DSM_NODE_ID}/${GAME_ID}/${DSM_INSTANCE_ID}"

}



# =============================================================
# Runtime directory
# =============================================================

get_instance_runtime()
{
    echo "$(get_instance_path)/runtime"
}


# =============================================================
# Launcher
# =============================================================

get_instance_launcher()
{
    echo "$(get_instance_path)/launcher.sh"
}


# =============================================================
# Configuração
# =============================================================

get_instance_config()
{
    echo "$(get_instance_path)/instance.conf"
}


# =============================================================
# PID
# =============================================================

get_instance_pidfile()
{
    echo "$(get_instance_runtime)/process.pid"
}


# =============================================================
# Logs
# =============================================================

get_instance_log()
{
    echo "$(get_instance_runtime)/instance.log"
}


# =============================================================
# Export API
# =============================================================

export -f runtime_validate

export -f runtime_game
export -f runtime_instance
export -f runtime_node
export -f runtime_host

export -f get_instance_path
export -f get_instance_runtime
export -f get_instance_launcher
export -f get_instance_config
export -f get_instance_pidfile
export -f get_instance_log