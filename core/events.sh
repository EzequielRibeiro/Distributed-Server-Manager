#!/bin/bash

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

EVENT_QUEUE="$DSM_ROOT/runtime/events/queue.json"



event_init()
{
    mkdir -p "$(dirname "$EVENT_QUEUE")"

    if [ ! -f "$EVENT_QUEUE" ]
    then
        echo "[]" > "$EVENT_QUEUE"
    fi


    if ! jq empty "$EVENT_QUEUE" >/dev/null 2>&1
    then
        echo "[]" > "$EVENT_QUEUE"
    fi
}



event_generate_id()
{
    echo "evt-$(cat /proc/sys/kernel/random/uuid | cut -c1-8)"
}



# =============================================================
# DSM Event Engine
#
# dsm_event
#
# TYPE
# CATEGORY
# SEVERITY
# MESSAGE
# SOURCE
# SERVER
# GAME
# INSTANCE
#
# =============================================================

dsm_event()
{
    local TYPE="$1"
    local CATEGORY="$2"
    local SEVERITY="$3"
    local MESSAGE="$4"

    local SOURCE="${5:-DSM}"

    local SERVER="${6:-}"
    local GAME="${7:-}"
    local INSTANCE="${8:-}"


    event_init


    local ID
    local TIMESTAMP

    ID=$(event_generate_id)

    TIMESTAMP=$(date +%s)


    local TMP

    TMP="$EVENT_QUEUE.tmp"



    jq \
    --arg id "$ID" \
    --arg type "$TYPE" \
    --arg category "$CATEGORY" \
    --arg severity "$SEVERITY" \
    --arg source "$SOURCE" \
    --arg message "$MESSAGE" \
    --arg server "$SERVER" \
    --arg game "$GAME" \
    --arg instance "$INSTANCE" \
    --argjson timestamp "$TIMESTAMP" \
'
. +=
[

    {
        id:$id,

        type:$type,

        category:$category,

        severity:$severity,

        source:$source,

        timestamp:$timestamp,


        resource:
        {
            server:
            (
                if $server == ""
                then null
                else $server
                end
            ),

            game:
            (
                if $game == ""
                then null
                else $game
                end
            ),

            instance:
            (
                if $instance == ""
                then null
                else $instance
                end
            )
        },


        data:
        {
            message:$message
        }
    }

]
' \
"$EVENT_QUEUE" > "$TMP"



    mv "$TMP" "$EVENT_QUEUE"
}


# =============================================================
# INFO
# =============================================================

event_info()
{
    local TYPE="$1"
    local CATEGORY="$2"
    local MESSAGE="$3"

    local SOURCE="${4:-DSM}"

    local SERVER="${5:-}"
    local GAME="${6:-}"
    local INSTANCE="${7:-}"


    dsm_event \
    "$TYPE" \
    "$CATEGORY" \
    "INFO" \
    "$MESSAGE" \
    "$SOURCE" \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"
}

# =============================================================
# WARNING
# =============================================================

event_warning()
{
    local TYPE="$1"
    local CATEGORY="$2"
    local MESSAGE="$3"

    local SOURCE="${4:-DSM}"

    local SERVER="${5:-}"
    local GAME="${6:-}"
    local INSTANCE="${7:-}"


    dsm_event \
    "$TYPE" \
    "$CATEGORY" \
    "WARNING" \
    "$MESSAGE" \
    "$SOURCE" \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"
}


# =============================================================
# ERROR
# =============================================================

event_error()
{
    local TYPE="$1"
    local CATEGORY="$2"
    local MESSAGE="$3"

    local SOURCE="${4:-DSM}"

    local SERVER="${5:-}"
    local GAME="${6:-}"
    local INSTANCE="${7:-}"


    dsm_event \
    "$TYPE" \
    "$CATEGORY" \
    "ERROR" \
    "$MESSAGE" \
    "$SOURCE" \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"
}


# =============================================================
# SUCCESS
# =============================================================

event_success()
{
    local TYPE="$1"
    local CATEGORY="$2"
    local MESSAGE="$3"

    local SOURCE="${4:-DSM}"

    local SERVER="${5:-}"
    local GAME="${6:-}"
    local INSTANCE="${7:-}"


    dsm_event \
    "$TYPE" \
    "$CATEGORY" \
    "SUCCESS" \
    "$MESSAGE" \
    "$SOURCE" \
    "$SERVER" \
    "$GAME" \
    "$INSTANCE"
}

# =============================================================
# DSM Event Engine - JSON
#
# dsm_event_json
#
# TYPE
# CATEGORY
# SEVERITY
# DATA_JSON
# SOURCE
# SERVER
# GAME
# INSTANCE
#
# Exemplo:
#
# dsm_event_json \
#     "UPDATE_COMPLETED" \
#     "installation" \
#     "INFO" \
#     '{"previous_version":"1","version":"2"}' \
#     "Capivara" \
#     "Node1" \
#     "dayz" \
#     ""
#
# =============================================================

dsm_event_json()
{
    local TYPE="${1:-}"
    local CATEGORY="${2:-}"
    local SEVERITY="${3:-}"
    local DATA_JSON="${4:-}"

    local SOURCE="${5:-DSM}"
    local SERVER="${6:-}"
    local GAME="${7:-}"
    local INSTANCE="${8:-}"

    local ID
    local TIMESTAMP
    local TMP

    # ---------------------------------------------------------
    # Validar parâmetros
    # ---------------------------------------------------------

    if [[ -z "${TYPE}" ]]
    then
        echo "[DSM][EVENT][ERRO] TYPE não informado." >&2
        return 1
    fi

    if [[ -z "${CATEGORY}" ]]
    then
        echo "[DSM][EVENT][ERRO] CATEGORY não informado." >&2
        return 1
    fi

    if [[ -z "${SEVERITY}" ]]
    then
        echo "[DSM][EVENT][ERRO] SEVERITY não informado." >&2
        return 1
    fi

    if [[ -z "${DATA_JSON}" ]]
    then
        DATA_JSON='{}'
    fi

    # ---------------------------------------------------------
    # Validar JSON
    # ---------------------------------------------------------

    if ! jq -e 'type == "object"' \
        >/dev/null 2>&1 <<< "${DATA_JSON}"
    then
        echo "[DSM][EVENT][ERRO] DATA_JSON inválido." >&2
        return 1
    fi

    # ---------------------------------------------------------
    # Preparar fila
    # ---------------------------------------------------------

    event_init

    ID="$(event_generate_id)"
    TIMESTAMP="$(date +%s)"

    TMP="${EVENT_QUEUE}.tmp.$$"

    # ---------------------------------------------------------
    # Publicar evento estruturado
    # ---------------------------------------------------------

    if ! jq \
        --arg id "${ID}" \
        --arg type "${TYPE}" \
        --arg category "${CATEGORY}" \
        --arg severity "${SEVERITY}" \
        --arg source "${SOURCE}" \
        --arg server "${SERVER}" \
        --arg game "${GAME}" \
        --arg instance "${INSTANCE}" \
        --argjson timestamp "${TIMESTAMP}" \
        --argjson data "${DATA_JSON}" \
        '
        . +=
        [
            {
                id: $id,

                type: $type,

                category: $category,

                severity: $severity,

                source: $source,

                timestamp: $timestamp,

                resource:
                {
                    server:
                    (
                        if $server == ""
                        then null
                        else $server
                        end
                    ),

                    game:
                    (
                        if $game == ""
                        then null
                        else $game
                        end
                    ),

                    instance:
                    (
                        if $instance == ""
                        then null
                        else $instance
                        end
                    )
                },

                data: $data
            }
        ]
        ' \
        "${EVENT_QUEUE}" > "${TMP}"
    then
        rm -f "${TMP}"
        echo "[DSM][EVENT][ERRO] Falha ao gerar evento." >&2
        return 1
    fi

    # ---------------------------------------------------------
    # Validar resultado
    # ---------------------------------------------------------

    if ! jq empty "${TMP}" >/dev/null 2>&1
    then
        rm -f "${TMP}"
        echo "[DSM][EVENT][ERRO] Evento gerou queue inválida." >&2
        return 1
    fi

    # ---------------------------------------------------------
    # Troca atômica
    # ---------------------------------------------------------

    if ! mv -- "${TMP}" "${EVENT_QUEUE}"
    then
        rm -f "${TMP}"
        echo "[DSM][EVENT][ERRO] Falha ao atualizar Event Queue." >&2
        return 1
    fi

    return 0
}

export -f dsm_event_json