#!/bin/sh
#
# ==============================================================================
# DSM Universal Runtime
# Runtime API
# ==============================================================================
#
# Responsabilidades
#
#   • Contexto do servidor
#   • Manifesto do Driver
#   • API utilizada pelos módulos
#   • Carregamento de Drivers
#
# Nenhum módulo do DSM deve acessar variáveis do Driver diretamente.
#
# ==============================================================================

#
# Prefixo interno
#
DSM_CONTEXT_PREFIX="DSM_CTX_"

###############################################################################
# Inicialização
###############################################################################

runtime_init()
{
    runtime_context_init
}

###############################################################################
# Contexto
###############################################################################

runtime_set()
{
    section="$1"
    key="$2"
    value="$3"

    export "DSM_CTX_${section}_${key}=${value}"
}

runtime_get()
{
    section="$1"
    key="$2"

    section=$(printf "%s" "$section" | tr '[:lower:]' '[:upper:]')
    key=$(printf "%s" "$key" | tr '[:lower:]' '[:upper:]')

    eval "printf '%s' \"\${DSM_CTX_${section}_${key}}\""
}

runtime_has()
{
    value=$(runtime_get "$1" "$2")

    [ -n "$value" ]
}

runtime_unset()
{
    local key="$1"

    unset "${DSM_CONTEXT_PREFIX}${key}"
}

runtime_clear()
{
    env |
    grep "^${DSM_CONTEXT_PREFIX}" |
    cut -d= -f1 |
    while read -r var
    do
        unset "$var"
    done
}

###############################################################################
# Manifesto
###############################################################################

runtime_manifest_set()
{
    runtime_set "$1" "$2"
}

runtime_manifest_get()
{
    runtime_get "$1"
}

runtime_manifest_has()
{
    runtime_has "$1"
}

###############################################################################
# Driver
###############################################################################

runtime_load_driver()
{
    runtime_driver_load "$1"
}

runtime_driver()
{
    runtime_driver_name
}

runtime_driver_call()
{
    runtime_driver_call "$@"
}

###############################################################################
# Informações
###############################################################################

runtime_game()
{
    runtime_get GAME
}

runtime_name()
{
    runtime_get NAME
}

runtime_server()
{
    runtime_get SERVER
}

runtime_instance()
{
    runtime_get INSTANCE
}

runtime_process()
{
    runtime_get PROCESS
}

runtime_log_dir()
{
    runtime_get LOG_DIR
}

runtime_profile_dir()
{
    runtime_get PROFILE_DIR
}

runtime_mod_dir()
{
    runtime_get MOD_DIR
}

runtime_backup_dir()
{
    runtime_get BACKUP_DIR
}

runtime_config_dir()
{
    runtime_get CONFIG_DIR
}

runtime_workshop_dir()
{
    runtime_get WORKSHOP_DIR
}

###############################################################################
# Capacidades
###############################################################################

runtime_supports()
{
    local feature="$1"

    runtime_get "SUPPORTS_${feature}"
}

###############################################################################
# Dump
###############################################################################

runtime_dump()
{
    echo

    echo "================ Runtime ================"

    env |
    grep "^${DSM_CONTEXT_PREFIX}" |
    sort

    echo
}

###############################################################################
# Informações resumidas
###############################################################################

runtime_info()
{
    cat <<EOF
Game............... $(runtime_game)
Name............... $(runtime_name)
Server............. $(runtime_server)
Process............ $(runtime_process)
Driver............. $(runtime_driver)
EOF
}