#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
#
# Process Context
#
# Responsável por:
#
# - Definir contexto do processo atual
# - Identificar node
# - Identificar jogo
# - Identificar instância
# - Padronizar informações para Process Manager
#
# =============================================================


set -Eeuo pipefail


# =============================================================
# Context Defaults
# =============================================================


context_load()
{

    export DSM_NODE="${DSM_NODE:-unknown}"

    export DSM_GAME="${DSM_GAME:-unknown}"

    export DSM_INSTANCE="${DSM_INSTANCE:-unknown}"

    export DSM_SERVER="${DSM_SERVER:-unknown}"

    export DSM_PROVIDER="${DSM_PROVIDER:-native}"

}



# =============================================================
# Getters
# =============================================================


process_context_node()
{
    echo "${DSM_NODE}"
}


process_context_game()
{
    echo "${DSM_GAME}"
}


process_context_instance()
{
    echo "${DSM_INSTANCE}"
}


process_context_server()
{
    echo "${DSM_SERVER}"
}


process_context_provider()
{
    echo "${DSM_PROVIDER}"
}



# =============================================================
# JSON Context
# =============================================================


process_context_json()
{

cat <<EOF
{
    "node":"${DSM_NODE}",
    "server":"${DSM_SERVER}",
    "game":"${DSM_GAME}",
    "instance":"${DSM_INSTANCE}",
    "provider":"${DSM_PROVIDER}"
}
EOF

}



# =============================================================
# Inicialização automática
# =============================================================

context_load