#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Installation State Manager
#
# Responsável por:
#
# - persistir estado da instalação
# - registrar provider
# - registrar versão/build
# - registrar status
# - registrar disponibilidade de rollback
# - registrar última ação
# - registrar resultado
#
# Destino:
#
# /opt/dsm/runtime/state/<node>/<game>/install.json
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# =============================================================
# Logger
# =============================================================

install_state_log()
{
    echo "[DSM][STATE] $*"
}

install_state_error()
{
    echo "[DSM][STATE][ERRO] $*" >&2
}

# =============================================================
# Dependências
# =============================================================

install_state_check_dependencies()
{
    if ! command -v jq >/dev/null 2>&1
    then
        install_state_error "jq não encontrado."
        return 1
    fi

    return 0
}

# =============================================================
# Resolver Node ID
# =============================================================

install_state_node_id()
{
    if [[ -n "${DSM_NODE_ID:-}" ]]
    then
        echo "${DSM_NODE_ID}"
        return 0
    fi

    # Fallback para hostname.
    hostname -s
}

# =============================================================
# Diretório de estado
# =============================================================

install_state_dir()
{
    local GAME_ID="$1"
    local NODE_ID

    NODE_ID="$(install_state_node_id)"

    echo "${DSM_ROOT}/runtime/state/${NODE_ID}/${GAME_ID}"
}

# =============================================================
# Arquivo de estado
# =============================================================

install_state_file()
{
    local GAME_ID="$1"

    echo "$(install_state_dir "${GAME_ID}")/install.json"
}

# =============================================================
# Timestamp
# =============================================================

install_state_timestamp()
{
    date +%s
}

# =============================================================
# Criar estado inicial
# =============================================================

install_state_init()
{
    local GAME_ID="$1"
    local PROVIDER="${2:-unknown}"

    local STATE_DIR
    local STATE_FILE
    local NODE_ID
    local TIMESTAMP

    install_state_check_dependencies || return 1

    STATE_DIR="$(install_state_dir "${GAME_ID}")"
    STATE_FILE="$(install_state_file "${GAME_ID}")"
    NODE_ID="$(install_state_node_id)"
    TIMESTAMP="$(install_state_timestamp)"

    mkdir -p "${STATE_DIR}"

    jq -n \
        --arg node "${NODE_ID}" \
        --arg game "${GAME_ID}" \
        --arg provider "${PROVIDER}" \
        --arg version "unknown" \
        --arg status "unknown" \
        --arg action "none" \
        --arg result "unknown" \
        --argjson rollback false \
        --argjson timestamp "${TIMESTAMP}" \
        '{
            identity: {
                node: $node,
                game: $game
            },
            installation: {
                provider: $provider,
                version: $version,
                status: $status,
                rollback_available: $rollback
            },
            operation: {
                last_action: $action,
                last_result: $result
            },
            timestamp: $timestamp
        }' > "${STATE_FILE}"

    install_state_log "Estado inicial criado:"
    install_state_log "${STATE_FILE}"

    return 0
}

# =============================================================
# Publicar estado
#
# Uso:
#
# install_state_publish \
#   game \
#   provider \
#   version \
#   status \
#   rollback \
#   action \
#   result
#
# =============================================================

install_state_publish()
{
    local GAME_ID="${1:-}"
    local PROVIDER="${2:-unknown}"
    local VERSION="${3:-unknown}"
    local STATUS="${4:-unknown}"
    local ROLLBACK="${5:-false}"
    local ACTION="${6:-none}"
    local RESULT="${7:-unknown}"

    local STATE_DIR
    local STATE_FILE
    local TEMP_FILE
    local NODE_ID
    local TIMESTAMP

    install_state_check_dependencies || return 1

    if [[ -z "${GAME_ID}" ]]
    then
        install_state_error "GAME_ID não informado."
        return 1
    fi

    case "${ROLLBACK}" in
        true|false)
            ;;
        yes)
            ROLLBACK=true
            ;;
        no)
            ROLLBACK=false
            ;;
        *)
            install_state_error "ROLLBACK inválido: ${ROLLBACK}"
            return 1
            ;;
    esac

    NODE_ID="$(install_state_node_id)"
    TIMESTAMP="$(install_state_timestamp)"

    STATE_DIR="$(install_state_dir "${GAME_ID}")"
    STATE_FILE="$(install_state_file "${GAME_ID}")"

    TEMP_FILE="${STATE_FILE}.tmp.$$"

    mkdir -p "${STATE_DIR}"

    # ---------------------------------------------------------
    # Escrita atômica do JSON
    # ---------------------------------------------------------

    if ! jq -n \
        --arg node "${NODE_ID}" \
        --arg game "${GAME_ID}" \
        --arg provider "${PROVIDER}" \
        --arg version "${VERSION}" \
        --arg status "${STATUS}" \
        --arg action "${ACTION}" \
        --arg result "${RESULT}" \
        --argjson rollback "${ROLLBACK}" \
        --argjson timestamp "${TIMESTAMP}" \
        '{
            identity: {
                node: $node,
                game: $game
            },
            installation: {
                provider: $provider,
                version: $version,
                status: $status,
                rollback_available: $rollback
            },
            operation: {
                last_action: $action,
                last_result: $result
            },
            timestamp: $timestamp
        }' > "${TEMP_FILE}"
    then
        install_state_error "Falha ao gerar estado."
        rm -f "${TEMP_FILE}"
        return 1
    fi

    if ! jq empty "${TEMP_FILE}" >/dev/null 2>&1
    then
        install_state_error "JSON de estado inválido."
        rm -f "${TEMP_FILE}"
        return 1
    fi

    mv -- "${TEMP_FILE}" "${STATE_FILE}"

    install_state_log "Estado publicado:"
    install_state_log "${STATE_FILE}"

    return 0
}

# =============================================================
# Obter estado
# =============================================================

install_state_get()
{
    local GAME_ID="$1"
    local STATE_FILE

    STATE_FILE="$(install_state_file "${GAME_ID}")"

    if [[ ! -f "${STATE_FILE}" ]]
    then
        return 1
    fi

    cat "${STATE_FILE}"
}

# =============================================================
# Status
# =============================================================

install_state_status()
{
    local GAME_ID="$1"

    local STATE_FILE

    STATE_FILE="$(install_state_file "${GAME_ID}")"

    if [[ ! -f "${STATE_FILE}" ]]
    then
        echo "unknown"
        return 1
    fi

    jq -r '.installation.status // "unknown"' "${STATE_FILE}"
}

# =============================================================
# Version
# =============================================================

install_state_version()
{
    local GAME_ID="$1"

    local STATE_FILE

    STATE_FILE="$(install_state_file "${GAME_ID}")"

    if [[ ! -f "${STATE_FILE}" ]]
    then
        echo "unknown"
        return 1
    fi

    jq -r '.installation.version // "unknown"' "${STATE_FILE}"
}

# =============================================================
# Rollback
# =============================================================

install_state_rollback_available()
{
    local GAME_ID="$1"

    local STATE_FILE

    STATE_FILE="$(install_state_file "${GAME_ID}")"

    if [[ ! -f "${STATE_FILE}" ]]
    then
        return 1
    fi

    [[ "$(jq -r '.installation.rollback_available // false' "${STATE_FILE}")" == "true" ]]
}

# =============================================================
# Mostrar estado formatado
# =============================================================

install_state_show()
{
    local GAME_ID="$1"
    local STATE_FILE

    STATE_FILE="$(install_state_file "${GAME_ID}")"

    if [[ ! -f "${STATE_FILE}" ]]
    then
        install_state_error "Estado não encontrado:"
        install_state_error "${STATE_FILE}"
        return 1
    fi

    jq . "${STATE_FILE}"
}

# =============================================================
# Remover estado
# =============================================================

install_state_remove()
{
    local GAME_ID="$1"
    local STATE_FILE

    STATE_FILE="$(install_state_file "${GAME_ID}")"

    if [[ -f "${STATE_FILE}" ]]
    then
        rm -f "${STATE_FILE}"

        install_state_log "Estado removido:"
        install_state_log "${STATE_FILE}"
    fi

    return 0
}

# =============================================================
# Export API
# =============================================================

export -f install_state_check_dependencies
export -f install_state_node_id
export -f install_state_dir
export -f install_state_file
export -f install_state_timestamp

export -f install_state_init
export -f install_state_publish
export -f install_state_get
export -f install_state_status
export -f install_state_version
export -f install_state_rollback_available
export -f install_state_show
export -f install_state_remove