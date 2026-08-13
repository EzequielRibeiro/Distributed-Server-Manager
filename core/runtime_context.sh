#!/bin/bash
# =============================================================
# DSM Runtime Context
#
# Define o ambiente atual de execução
#
# Host / Game / Instance
#
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# Host físico ou agente DSM
# Prioridade:
# 1 - contexto runtime
# 2 - configuração DSM
# 3 - hostname

RUNTIME_HOST="${DSM_HOST:-unknown}"

RUNTIME_NODE="${DSM_NODE:-unknown}"

# Jogo atual
# Prioridade:
# 1 - contexto runtime
# 2 - configuração DSM

RUNTIME_GAME="${DSM_GAME:-unknown}"


# Instância atual

RUNTIME_INSTANCE="${DSM_INSTANCE:-default}"



runtime_host()
{
echo "$RUNTIME_HOST"
}



runtime_game()
{
echo "$RUNTIME_GAME"
}



runtime_instance()
{
echo "$RUNTIME_INSTANCE"
}

runtime_node()
{
    echo "$RUNTIME_NODE"
}

runtime_context()
{
cat <<EOF
{
  "host":"$RUNTIME_HOST",
  "node":"$RUNTIME_NODE",
  "game":"$RUNTIME_GAME",
  "instance":"$RUNTIME_INSTANCE"
}
EOF
}