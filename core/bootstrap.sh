#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Core Bootstrap
#
# Inicialização do ambiente DSM
#
# =============================================================

set -Eeuo pipefail

# -------------------------------------------------------------
# Evita carregamento duplicado
# -------------------------------------------------------------
if [[ "${DSM_BOOTSTRAP_LOADED:-0}" == "1" ]]
then

    if [[ "${BASH_SOURCE[0]}" != "$0" ]]
    then
        return 0
    else
        exit 0
    fi

fi

export DSM_BOOTSTRAP_LOADED=1

# -------------------------------------------------------------
# DSM Root
# -------------------------------------------------------------
export DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# -------------------------------------------------------------
# Configuração principal
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/config/dsm.conf" ]] \
    && source "${DSM_ROOT}/config/dsm.conf"

# -------------------------------------------------------------
# Runtime Global
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/config/runtime.sh" ]] \
    && source "${DSM_ROOT}/config/runtime.sh"

# -------------------------------------------------------------
# Logger
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/core/logger.sh" ]] \
    && source "${DSM_ROOT}/core/logger.sh"

# -------------------------------------------------------------
# Config Library
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/core/config.sh" ]] \
    && source "${DSM_ROOT}/core/config.sh"

# -------------------------------------------------------------
# Semantic Versioning Library
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/core/semver.sh" ]] \
    && source "${DSM_ROOT}/core/semver.sh"

# -------------------------------------------------------------
# Runtime Publisher
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/core/runtime/publisher.sh" ]] \
&& source "${DSM_ROOT}/core/runtime/publisher.sh"

# -------------------------------------------------------------
# Process Engine
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/core/process/process.sh" ]] \
    && source "${DSM_ROOT}/core/process/process.sh"

[[ -f "${DSM_ROOT}/core/process/pid.sh" ]] \
    && source "${DSM_ROOT}/core/process/pid.sh"

[[ -f "${DSM_ROOT}/core/process/tree.sh" ]] \
    && source "${DSM_ROOT}/core/process/tree.sh"

[[ -f "${DSM_ROOT}/core/process/manager.sh" ]] \
    && source "${DSM_ROOT}/core/process/manager.sh"

# -------------------------------------------------------------
# Server Library
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/core/server.sh" ]] \
    && source "${DSM_ROOT}/core/server.sh"

# -------------------------------------------------------------
# Game Loader
# -------------------------------------------------------------
[[ -f "${DSM_ROOT}/core/game_loader.sh" ]] \
    && source "${DSM_ROOT}/core/game_loader.sh"

# -------------------------------------------------------------
# Ambiente
# -------------------------------------------------------------
dsm_environment() {

    cat <<EOF

============================================================
 Capivara DSM Environment
============================================================

DSM Root      : ${DSM_ROOT}
Node          : ${DSM_NODE_ID}
Game          : ${GAME_ID:-}
Instance      : ${DSM_INSTANCE_ID:-}

Config        : ${DSM_CONFIG_DIR}
Runtime       : ${DSM_RUNTIME_DIR}
Logs          : ${DSM_LOG_DIR}

Instance Root : ${INSTANCE_ROOT}

============================================================

EOF

}

# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    dsm_environment
fi
