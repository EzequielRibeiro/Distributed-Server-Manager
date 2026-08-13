#!/bin/sh
#
# DSM - Universal Runtime
# bootstrap.sh
#
# Inicializa o Runtime Universal.
#

# Evita múltiplos carregamentos
[ -n "${DSM_RUNTIME_BOOTSTRAP:-}" ] && return 0
DSM_RUNTIME_BOOTSTRAP=1

RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"

#
# Bibliotecas
#
. "$RUNTIME_DIR/context.sh"
. "$RUNTIME_DIR/registry.sh"
. "$RUNTIME_DIR/discovery.sh"
. "$RUNTIME_DIR/state.sh"
. "$RUNTIME_DIR/runtime.sh"

#
# Driver Genérico
#
. "$RUNTIME_DIR/drivers/generic.sh"

#
# Inicialização
#
runtime_bootstrap()
{
    runtime_context_init

    runtime_discover

    runtime_load_driver

    runtime_registry_init

    runtime_state_init
}

#
# Executa automaticamente
#
runtime_bootstrap