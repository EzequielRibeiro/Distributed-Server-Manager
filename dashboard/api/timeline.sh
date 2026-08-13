#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Dashboard API - Timeline
#
# Responsável por:
#
# - consultar Universal Event History
# - ordenar eventos por timestamp
# - limitar resultados
# - filtrar por categoria
# - fornecer estatísticas
#
# Fonte:
#
# /opt/dsm/runtime/events/history.json
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

HISTORY_FILE="${DSM_ROOT}/runtime/events/history.json"

# =============================================================
# HTTP Header
# =============================================================

api_header()
{
    echo "Content-Type: application/json"
    echo ""
}

# =============================================================
# Inicialização
# =============================================================

history_init()
{
    mkdir -p "$(dirname "${HISTORY_FILE}")"

    if [[ ! -f "${HISTORY_FILE}" ]]
    then
        echo "[]" > "${HISTORY_FILE}"
    fi

    # ---------------------------------------------------------
    # Garantir arquivo JSON válido
    # ---------------------------------------------------------

    if ! jq -e 'type == "array"' \
        "${HISTORY_FILE}" >/dev/null 2>&1
    then
        echo "[]" > "${HISTORY_FILE}"
    fi
}

# =============================================================
# Timeline
#
# Uso:
#
# timeline_json 20
#
# =============================================================

timeline_json()
{
    local LIMIT="${1:-20}"

    history_init

    # ---------------------------------------------------------
    # Sanitizar limite
    # ---------------------------------------------------------

    if ! [[ "${LIMIT}" =~ ^[0-9]+$ ]]
    then
        LIMIT=20
    fi

    jq \
        --argjson limit "${LIMIT}" \
        '
        sort_by(.timestamp // 0)
        | reverse
        | .[0:$limit]
        ' \
        "${HISTORY_FILE}"
}

# =============================================================
# Timeline por categoria
#
# Exemplo:
#
# timeline_category installation 20
#
# =============================================================

timeline_category()
{
    local CATEGORY="${1:-}"
    local LIMIT="${2:-20}"

    history_init

    if [[ -z "${CATEGORY}" ]]
    then
        timeline_json "${LIMIT}"
        return
    fi

    if ! [[ "${LIMIT}" =~ ^[0-9]+$ ]]
    then
        LIMIT=20
    fi

    jq \
        --arg category "${CATEGORY}" \
        --argjson limit "${LIMIT}" \
        '
        [
            .[]
            | select(.category == $category)
        ]
        | sort_by(.timestamp // 0)
        | reverse
        | .[0:$limit]
        ' \
        "${HISTORY_FILE}"
}

# =============================================================
# Timeline por tipo
# =============================================================

timeline_type()
{
    local TYPE="${1:-}"
    local LIMIT="${2:-20}"

    history_init

    if [[ -z "${TYPE}" ]]
    then
        timeline_json "${LIMIT}"
        return
    fi

    if ! [[ "${LIMIT}" =~ ^[0-9]+$ ]]
    then
        LIMIT=20
    fi

    jq \
        --arg type "${TYPE}" \
        --argjson limit "${LIMIT}" \
        '
        [
            .[]
            | select(.type == $type)
        ]
        | sort_by(.timestamp // 0)
        | reverse
        | .[0:$limit]
        ' \
        "${HISTORY_FILE}"
}

# =============================================================
# Timeline por Game
#
# Schema universal:
#
# resource.game
#
# =============================================================

timeline_game()
{
    local GAME_ID="${1:-}"
    local LIMIT="${2:-20}"

    history_init

    if [[ -z "${GAME_ID}" ]]
    then
        timeline_json "${LIMIT}"
        return
    fi

    if ! [[ "${LIMIT}" =~ ^[0-9]+$ ]]
    then
        LIMIT=20
    fi

    jq \
        --arg game "${GAME_ID}" \
        --argjson limit "${LIMIT}" \
        '
        [
            .[]
            | select(.resource.game == $game)
        ]
        | sort_by(.timestamp // 0)
        | reverse
        | .[0:$limit]
        ' \
        "${HISTORY_FILE}"
}

# =============================================================
# Timeline por Node / Server
#
# Schema universal:
#
# resource.server
#
# =============================================================

timeline_server()
{
    local SERVER_ID="${1:-}"
    local LIMIT="${2:-20}"

    history_init

    if [[ -z "${SERVER_ID}" ]]
    then
        timeline_json "${LIMIT}"
        return
    fi

    if ! [[ "${LIMIT}" =~ ^[0-9]+$ ]]
    then
        LIMIT=20
    fi

    jq \
        --arg server "${SERVER_ID}" \
        --argjson limit "${LIMIT}" \
        '
        [
            .[]
            | select(.resource.server == $server)
        ]
        | sort_by(.timestamp // 0)
        | reverse
        | .[0:$limit]
        ' \
        "${HISTORY_FILE}"
}

# =============================================================
# Estatísticas
# =============================================================

timeline_stats()
{
    history_init

    jq '
    {
        total: length,

        info:
        (
            [
                .[]
                | select(.severity == "INFO")
            ]
            | length
        ),

        warning:
        (
            [
                .[]
                | select(.severity == "WARNING")
            ]
            | length
        ),

        error:
        (
            [
                .[]
                | select(.severity == "ERROR")
            ]
            | length
        ),

        critical:
        (
            [
                .[]
                | select(.severity == "CRITICAL")
            ]
            | length
        ),

        installation:
        (
            [
                .[]
                | select(.category == "installation")
            ]
            | length
        ),

        server:
        (
            [
                .[]
                | select(.category == "server")
            ]
            | length
        ),

        recovery:
        (
            [
                .[]
                | select(.type == "RECOVERY")
            ]
            | length
        )
    }
    ' \
    "${HISTORY_FILE}"
}

# =============================================================
# Dispatcher
# =============================================================

case "${1:-json}" in

    stats)

        api_header
        timeline_stats
    ;;

    json)

        api_header
        timeline_json "${2:-20}"
    ;;

    category)

        api_header
        timeline_category \
            "${2:-}" \
            "${3:-20}"
    ;;

    type)

        api_header
        timeline_type \
            "${2:-}" \
            "${3:-20}"
    ;;

    game)

        api_header
        timeline_game \
            "${2:-}" \
            "${3:-20}"
    ;;

    server)

        api_header
        timeline_server \
            "${2:-}" \
            "${3:-20}"
    ;;

    *)

        api_header
        timeline_json "${1:-20}"
    ;;

esac
