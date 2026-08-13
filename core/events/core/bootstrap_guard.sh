#!/bin/bash
# =============================================================
# core/bootstrap_guard.sh - MÓDULO 01 (CORE)
#
# Proteção contra carregamento múltiplo do bootstrap DSM.
#
# Evita:
# - source duplicado
# - funções redefinidas
# - loops de dependência
#
# Uso:
#
# source "$DSM_ROOT/core/bootstrap_guard.sh"
#
# if ! bootstrap_guard_check; then
#     return 0
# fi
#
# =============================================================

# =============================================================
# Variável global de controle
# =============================================================
DSM_BOOTSTRAP_LOADED="${DSM_BOOTSTRAP_LOADED:-0}"

# =============================================================
# Verifica se bootstrap já foi carregado
#
# Retorno:
#
# 0 = pode continuar
# 1 = já carregado
#
# =============================================================
bootstrap_guard_check()
{
    if [ "$DSM_BOOTSTRAP_LOADED" = "1" ]
    then
        return 1
    fi

    DSM_BOOTSTRAP_LOADED=1
    export DSM_BOOTSTRAP_LOADED

    return 0
}

# =============================================================
# Força reset da trava
#
# Uso:
#
# somente testes/manutenção
#
# =============================================================
bootstrap_guard_reset()
{
    DSM_BOOTSTRAP_LOADED=0
    export DSM_BOOTSTRAP_LOADED
}
