#!/usr/bin/env bash

# =============================================================
# Capivara DSM
#
# Doctor - Instance Context
#
# Responsável:
#   Construir contexto isolado de uma instância:
#
#   NODE / GAME / INSTANCE
#
# Não inicia, para ou reinicia processos.
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
INSTANCE_ROOT="${INSTANCE_ROOT:-${DSM_ROOT}/instances}"


doctor_instance_context_load()
{
    local INSTANCE_PATH="$1"

    if [[ -z "${INSTANCE_PATH}" ]] ||
       [[ ! -d "${INSTANCE_PATH}" ]]
    then
        echo "Instância inexistente: ${INSTANCE_PATH}" >&2
        return 1
    fi


    # ---------------------------------------------------------
    # Validar que está dentro de INSTANCE_ROOT
    # ---------------------------------------------------------

    local ROOT_REAL
    local INSTANCE_REAL

    ROOT_REAL="$(
        realpath -e "${INSTANCE_ROOT}" 2>/dev/null
    )" || return 1

    INSTANCE_REAL="$(
        realpath -e "${INSTANCE_PATH}" 2>/dev/null
    )" || return 1

    case "${INSTANCE_REAL}/" in
        "${ROOT_REAL}/"*)
            ;;
        *)
            echo \
                "Instância fora de INSTANCE_ROOT: ${INSTANCE_REAL}" \
                >&2
            return 1
            ;;
    esac


    # ---------------------------------------------------------
    # Identidade derivada do caminho
    # ---------------------------------------------------------

    local RELATIVE

    RELATIVE="${INSTANCE_REAL#${ROOT_REAL}/}"

    local PATH_NODE
    local PATH_GAME
    local PATH_INSTANCE
    local EXTRA

    IFS='/' read -r \
        PATH_NODE \
        PATH_GAME \
        PATH_INSTANCE \
        EXTRA \
        <<< "${RELATIVE}"

    if [[ -z "${PATH_NODE}" ]] ||
       [[ -z "${PATH_GAME}" ]] ||
       [[ -z "${PATH_INSTANCE}" ]] ||
       [[ -n "${EXTRA:-}" ]]
    then
        echo \
            "Estrutura de instância inválida: ${RELATIVE}" \
            >&2
        return 1
    fi


    # ---------------------------------------------------------
    # instance.conf obrigatório para contexto executável
    # ---------------------------------------------------------

    local CONFIG
    CONFIG="${INSTANCE_REAL}/instance.conf"

    if [[ ! -f "${CONFIG}" ]]
    then
        echo \
            "instance.conf ausente: ${CONFIG}" \
            >&2
        return 2
    fi


    # ---------------------------------------------------------
    # Carregar configuração em subshell
    #
    # O arquivo NÃO é carregado diretamente no shell chamador.
    # ---------------------------------------------------------

    local CONTEXT_JSON

    CONTEXT_JSON="$(
        INSTANCE_CONFIG="${CONFIG}" \
        PATH_NODE="${PATH_NODE}" \
        PATH_GAME="${PATH_GAME}" \
        PATH_INSTANCE="${PATH_INSTANCE}" \
        INSTANCE_REAL="${INSTANCE_REAL}" \
        bash --noprofile --norc <<'INNER'
set -Eeuo pipefail

unset \
    NODE_ID \
    GAME \
    GAME_ID \
    INSTANCE_ID \
    DSM_NODE_ID \
    DSM_INSTANCE_ID \
    GAME_INSTALL \
    SERVERFILES_PATH \
    LINUXGSM_PATH \
    LINUXGSM_BIN \
    INSTANCE_NAME \
    PROCESS_ENGINE \
    JAVA_BIN \
    EXECUTABLE \
    WORKING_DIR \
    ARGS \
    RUNTIME_ID \
    EDITION \
    VARIANT \
    GAME_VERSION \
    BUILD_ID

source "${INSTANCE_CONFIG}"

CONFIG_GAME="${GAME:-}"
CONFIG_INSTANCE="${INSTANCE_ID:-}"
CONFIG_NODE="${NODE_ID:-}"

if [[ -z "${CONFIG_GAME}" ]]
then
    CONFIG_GAME="${PATH_GAME}"
fi

if [[ -z "${CONFIG_INSTANCE}" ]]
then
    CONFIG_INSTANCE="${PATH_INSTANCE}"
fi

if [[ -z "${CONFIG_NODE}" ]]
then
    CONFIG_NODE="${PATH_NODE}"
fi

if [[ "${CONFIG_GAME,,}" != "${PATH_GAME,,}" ]]
then
    echo \
        "GAME divergente: path=${PATH_GAME}, config=${CONFIG_GAME}" \
        >&2
    exit 10
fi

if [[ "${CONFIG_INSTANCE}" != "${PATH_INSTANCE}" ]]
then
    echo \
        "INSTANCE_ID divergente: path=${PATH_INSTANCE}, config=${CONFIG_INSTANCE}" \
        >&2
    exit 11
fi

if [[ "${CONFIG_NODE}" != "${PATH_NODE}" ]]
then
    echo \
        "NODE_ID divergente: path=${PATH_NODE}, config=${CONFIG_NODE}" \
        >&2
    exit 12
fi

SERVERFILES="${GAME_INSTALL:-}"

if [[ -z "${SERVERFILES}" ]]
then
    if [[ -n "${SERVERFILES_PATH:-}" ]]
    then
        SERVERFILES="${SERVERFILES_PATH}"

    elif [[ -n "${WORKING_DIR:-}" ]]
    then
        if [[ "${WORKING_DIR}" = /* ]]
        then
            SERVERFILES="${WORKING_DIR}"
        else
            SERVERFILES="${INSTANCE_REAL}/${WORKING_DIR}"
        fi
    else
        SERVERFILES="${INSTANCE_REAL}/serverfiles"
    fi
fi

jq -nc \
    --arg node "${CONFIG_NODE}" \
    --arg game "${CONFIG_GAME,,}" \
    --arg instance "${CONFIG_INSTANCE}" \
    --arg path "${INSTANCE_REAL}" \
    --arg config "${INSTANCE_CONFIG}" \
    --arg serverfiles "${SERVERFILES}" \
    --arg process_engine "${PROCESS_ENGINE:-}" \
    --arg runtime_id "${RUNTIME_ID:-}" \
    --arg edition "${EDITION:-}" \
    --arg variant "${VARIANT:-}" \
    --arg version "${GAME_VERSION:-}" \
    --arg build "${BUILD_ID:-}" \
    --arg java_bin "${JAVA_BIN:-}" \
    --arg executable "${EXECUTABLE:-}" \
    --arg working_dir "${WORKING_DIR:-}" \
    --arg args "${ARGS:-}" \
    --arg linuxgsm_path "${LINUXGSM_PATH:-}" \
    --arg linuxgsm_bin "${LINUXGSM_BIN:-${INSTANCE_NAME:-}}" \
    '{
        node: $node,
        game: $game,
        instance: $instance,
        path: $path,
        config: $config,

        runtime: {
            id: $runtime_id,
            process_engine: $process_engine,
            edition: $edition,
            variant: $variant,
            version: $version,
            build: $build
        },

        process: {
            java_bin: $java_bin,
            executable: $executable,
            working_dir: $working_dir,
            args: $args
        },

        paths: {
            serverfiles: $serverfiles,
            linuxgsm: $linuxgsm_path
        },

        linuxgsm: {
            bin: $linuxgsm_bin
        }
    }'
INNER
    )" || return $?


    if ! jq -e . >/dev/null 2>&1 <<< "${CONTEXT_JSON}"
    then
        echo "Contexto JSON inválido." >&2
        return 1
    fi

    printf '%s\n' "${CONTEXT_JSON}"
}


doctor_instance_context_export()
{
    local INSTANCE_PATH="$1"

    local CONTEXT

    CONTEXT="$(
        doctor_instance_context_load \
            "${INSTANCE_PATH}"
    )" || return $?

    export DSM_NODE_ID
    export GAME_ID
    export DSM_INSTANCE_ID
    export INSTANCE_PATH
    export SERVERFILES_PATH

    DSM_NODE_ID="$(
        jq -r '.node' <<< "${CONTEXT}"
    )"

    GAME_ID="$(
        jq -r '.game' <<< "${CONTEXT}"
    )"

    DSM_INSTANCE_ID="$(
        jq -r '.instance' <<< "${CONTEXT}"
    )"

    INSTANCE_PATH="$(
        jq -r '.path' <<< "${CONTEXT}"
    )"

    SERVERFILES_PATH="$(
        jq -r '.paths.serverfiles' <<< "${CONTEXT}"
    )"

    export GAME="${GAME_ID}"
    export INSTANCE_ID="${DSM_INSTANCE_ID}"

    printf '%s\n' "${CONTEXT}"
}


if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    case "${1:-}" in

        show)
            doctor_instance_context_load \
                "${2:-}"
        ;;

        *)
            echo "Uso:"
            echo "  instance_context.sh show INSTANCE_PATH"
            exit 1
        ;;

    esac
fi
