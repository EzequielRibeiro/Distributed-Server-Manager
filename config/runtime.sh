#!/usr/bin/env bash

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

AGENT_CONFIG="${DSM_ROOT}/config/agent.conf"

# =============================================================
# Preservar contexto já definido
# =============================================================

_RUNTIME_NODE="${DSM_NODE_ID:-}"
_RUNTIME_ROOT="${INSTANCE_ROOT:-}"
_RUNTIME_GAME="${GAME_ID:-}"
_RUNTIME_INSTANCE="${DSM_INSTANCE_ID:-}"

# =============================================================
# Agent
# =============================================================

[[ -f "${AGENT_CONFIG}" ]] || {
    echo "Agent não configurado:"
    echo "${AGENT_CONFIG}"
    return 1 2>/dev/null || exit 1
}

source "${AGENT_CONFIG}"

# =============================================================
# Restaurar contexto
# =============================================================

[[ -n "${_RUNTIME_NODE}" ]] && DSM_NODE_ID="${_RUNTIME_NODE}"
[[ -n "${_RUNTIME_ROOT}" ]] && INSTANCE_ROOT="${_RUNTIME_ROOT}"
[[ -n "${_RUNTIME_GAME}" ]] && GAME_ID="${_RUNTIME_GAME}"
[[ -n "${_RUNTIME_INSTANCE}" ]] && DSM_INSTANCE_ID="${_RUNTIME_INSTANCE}"

# =============================================================
# Defaults
# =============================================================

DSM_NODE_ID="${DSM_NODE_ID:-}"
INSTANCE_ROOT="${INSTANCE_ROOT:-${DSM_ROOT}/instances}"

DSM_CONFIG_DIR="${DSM_ROOT}/config"
DSM_RUNTIME_DIR="${DSM_ROOT}/runtime"
DSM_LOG_DIR="${DSM_ROOT}/logs"

# =============================================================
# Export
# =============================================================

export DSM_ROOT
export DSM_CONFIG_DIR
export DSM_RUNTIME_DIR
export DSM_LOG_DIR

export DSM_NODE_ID
export INSTANCE_ROOT

export GAME_ID
export DSM_INSTANCE_ID

export DSM_USER
export DSM_GROUP

export AGENT_ID
export AGENT_NAME
export AGENT_STATUS

export CONTROLLER_ENDPOINT
export AGENT_TOKEN

export DSM_RUNTIME_LOADED=1

unset _RUNTIME_NODE
unset _RUNTIME_ROOT
unset _RUNTIME_GAME
unset _RUNTIME_INSTANCE


