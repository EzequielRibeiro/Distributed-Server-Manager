#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Provider Loader
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
PROVIDER_ROOT="${DSM_ROOT}/installer/providers"
CUSTOM_PROVIDER_ROOT="${DSM_CUSTOM_PROVIDER_ROOT:-${DSM_ROOT}/custom/providers}"
CUSTOM_PROVIDER_CONTRACT="${DSM_ROOT}/installer/custom_provider_contract.sh"

provider_loader_log()
{
    echo "[DSM][PROVIDER] $*"
}

provider_loader_error()
{
    echo "[DSM][PROVIDER][ERRO] $*" >&2
}

provider_loader_progress()
{
    local STAGE="${1:-processing}"
    local PROGRESS="${2:-0}"
    local MESSAGE="${3:-}"

    if declare -F install_operation_progress_safe >/dev/null 2>&1
    then
        install_operation_progress_safe "${STAGE}" "${PROGRESS}" "${MESSAGE}"
    fi
}

# =============================================================
# HTTP Progress Support
# =============================================================

provider_loader_http_content_length()
{
    local URL="${1:-}"
    local LENGTH=""

    [[ "${URL}" == http://* || "${URL}" == https://* ]] || return 1

    if command -v curl >/dev/null 2>&1
    then
        LENGTH="$(
            curl --silent --show-error --fail --location --head \
                --connect-timeout 10 --max-time 30 "${URL}" 2>/dev/null |
            tr -d '\r' |
            awk '
                BEGIN { IGNORECASE=1 }
                /^content-length:[[:space:]]*[0-9]+/ { value=$2 }
                END { if (value ~ /^[0-9]+$/) print value }
            '
        )" || true
    elif command -v wget >/dev/null 2>&1
    then
        LENGTH="$(
            wget --server-response --spider --timeout=10 --tries=1 "${URL}" 2>&1 |
            tr -d '\r' |
            awk '
                BEGIN { IGNORECASE=1 }
                /Content-Length:[[:space:]]*[0-9]+/ {
                    for (i=1; i<=NF; i++) if ($i ~ /^[0-9]+$/) value=$i
                }
                END { if (value ~ /^[0-9]+$/) print value }
            '
        )" || true
    fi

    if [[ "${LENGTH}" =~ ^[0-9]+$ ]] && (( LENGTH > 0 ))
    then
        echo "${LENGTH}"
        return 0
    fi

    return 1
}

provider_loader_http_bytes_written()
{
    local PATH_TO_CHECK="${1:-}"

    if [[ ! -e "${PATH_TO_CHECK}" ]]
    then
        echo 0
        return 0
    fi

    if command -v du >/dev/null 2>&1
    then
        du -sb --apparent-size "${PATH_TO_CHECK}" 2>/dev/null | awk '{print $1}'
        return 0
    fi

    echo 0
}

provider_loader_http_run_with_progress()
{
    local URL="${1:-}"
    local INSTALL_PATH="${2:-}"
    shift 2 || true

    local TOTAL_BYTES=""
    local CURRENT_BYTES=0
    local HTTP_PERCENT=0
    local CAP_PROGRESS=25
    local PID STATUS

    TOTAL_BYTES="$(provider_loader_http_content_length "${URL}" 2>/dev/null || true)"

    if [[ "${TOTAL_BYTES}" =~ ^[0-9]+$ ]] && (( TOTAL_BYTES > 0 ))
    then
        provider_loader_log "HTTP Content-Length: ${TOTAL_BYTES} bytes"
    else
        TOTAL_BYTES=""
        provider_loader_log "HTTP Content-Length indisponível; usando progresso por estágio."
    fi

    provider_install_base "${URL}" "${INSTALL_PATH}" "$@" &
    PID=$!

    while kill -0 "${PID}" 2>/dev/null
    do
        if [[ -n "${TOTAL_BYTES}" ]]
        then
            CURRENT_BYTES="$(provider_loader_http_bytes_written "${INSTALL_PATH}")"
            [[ "${CURRENT_BYTES}" =~ ^[0-9]+$ ]] || CURRENT_BYTES=0

            HTTP_PERCENT=$(( CURRENT_BYTES * 100 / TOTAL_BYTES ))
            (( HTTP_PERCENT < 0 )) && HTTP_PERCENT=0
            (( HTTP_PERCENT > 99 )) && HTTP_PERCENT=99
            CAP_PROGRESS=$((25 + (HTTP_PERCENT * 50 / 100)))

            provider_loader_progress "downloading" "${CAP_PROGRESS}" "HTTP: ${HTTP_PERCENT}%"
        fi
        sleep 1
    done

    if wait "${PID}"; then STATUS=0; else STATUS=$?; fi
    (( STATUS == 0 )) && provider_loader_progress "downloaded" 75 "HTTP: 100%"
    return "${STATUS}"
}

# =============================================================
# Provider discovery
# Built-ins always win; custom providers cannot silently replace
# an official provider with the same name.
# =============================================================

provider_loader_validate_name()
{
    local PROVIDER="${1:-}"

    if [[ -z "${PROVIDER}" ]]
    then
        provider_loader_error "Provider não informado."
        return 1
    fi

    if [[ ! "${PROVIDER}" =~ ^[a-zA-Z0-9_-]+$ ]]
    then
        provider_loader_error "Nome de provider inválido: ${PROVIDER}"
        return 1
    fi

    return 0
}

provider_loader_path()
{
    local PROVIDER="$1"
    local BUILTIN CUSTOM

    provider_loader_validate_name "${PROVIDER}" || return 1

    BUILTIN="${PROVIDER_ROOT}/${PROVIDER}.sh"
    CUSTOM="${CUSTOM_PROVIDER_ROOT}/${PROVIDER}.sh"

    if [[ -f "${BUILTIN}" ]]
    then
        echo "${BUILTIN}"
        return 0
    fi

    if [[ -f "${CUSTOM}" ]]
    then
        echo "${CUSTOM}"
        return 0
    fi

    return 1
}

provider_loader_origin()
{
    local FILE="${1:-}"
    case "${FILE}" in
        "${CUSTOM_PROVIDER_ROOT}"/*) echo custom ;;
        *) echo builtin ;;
    esac
}

provider_loader_exists()
{
    provider_loader_path "$1" >/dev/null 2>&1
}

provider_loader_file_mtime()
{
    local FILE="${1:-}"
    [[ -f "${FILE}" ]] || { echo 0; return 1; }
    stat -c %Y "${FILE}" 2>/dev/null || echo 0
}

provider_loader_unload()
{
    unset -f provider_ensure provider_install provider_update provider_verify \
        provider_info provider_version provider_install_base provider_update_base \
        2>/dev/null || true

    unset DSM_ACTIVE_PROVIDER DSM_ACTIVE_PROVIDER_FILE DSM_ACTIVE_PROVIDER_MTIME \
        DSM_ACTIVE_PROVIDER_ORIGIN DSM_PROVIDER_API_VERSION DSM_PROVIDER_KIND \
        DSM_PROVIDER_NAME 2>/dev/null || true

    return 0
}

provider_loader_validate_contract()
{
    local PROVIDER="$1"
    local ORIGIN="${2:-builtin}"

    if [[ "${ORIGIN}" == "custom" ]]
    then
        if [[ ! -f "${CUSTOM_PROVIDER_CONTRACT}" ]]
        then
            provider_loader_error "Custom Provider Contract não encontrado: ${CUSTOM_PROVIDER_CONTRACT}"
            return 1
        fi

        # shellcheck source=/dev/null
        source "${CUSTOM_PROVIDER_CONTRACT}"
        custom_provider_contract_validate "${PROVIDER}" || return 1
        return 0
    fi

    if ! declare -F provider_ensure >/dev/null 2>&1
    then
        provider_loader_error "Provider '${PROVIDER}' não implementa provider_ensure()."
        return 1
    fi

    if ! declare -F provider_install >/dev/null 2>&1
    then
        provider_loader_error "Provider '${PROVIDER}' não implementa provider_install()."
        return 1
    fi

    return 0
}

# =============================================================
# Universal progress wrapper
# =============================================================

provider_loader_wrap_progress()
{
    local ORIGINAL

    if declare -F provider_install >/dev/null 2>&1 && ! declare -F provider_install_base >/dev/null 2>&1
    then
        ORIGINAL="$(declare -f provider_install)"
        ORIGINAL="${ORIGINAL/provider_install ()/provider_install_base ()}"
        eval "${ORIGINAL}"

        provider_install()
        {
            provider_loader_progress "downloading" 25 "Provider ${DSM_ACTIVE_PROVIDER:-unknown} iniciado"

            if [[ "${DSM_ACTIVE_PROVIDER:-}" == "http" && "${1:-}" == http*://* ]]
            then
                if provider_loader_http_run_with_progress "$@"; then return 0; fi
                provider_loader_progress "downloading" 25 "Falha no provider http"
                return 1
            fi

            if provider_install_base "$@"
            then
                provider_loader_progress "downloaded" 75 \
                    "Arquivos obtidos pelo provider ${DSM_ACTIVE_PROVIDER:-unknown}"
                return 0
            fi

            provider_loader_progress "downloading" 25 \
                "Falha no provider ${DSM_ACTIVE_PROVIDER:-unknown}"
            return 1
        }

        export -f provider_install_base provider_install
    fi

    if declare -F provider_update >/dev/null 2>&1 && ! declare -F provider_update_base >/dev/null 2>&1
    then
        ORIGINAL="$(declare -f provider_update)"
        ORIGINAL="${ORIGINAL/provider_update ()/provider_update_base ()}"
        eval "${ORIGINAL}"

        provider_update()
        {
            provider_loader_progress "downloading" 25 \
                "Atualização via provider ${DSM_ACTIVE_PROVIDER:-unknown} iniciada"

            if provider_update_base "$@"
            then
                provider_loader_progress "downloaded" 75 \
                    "Atualização obtida pelo provider ${DSM_ACTIVE_PROVIDER:-unknown}"
                return 0
            fi

            provider_loader_progress "downloading" 25 \
                "Falha na atualização via provider ${DSM_ACTIVE_PROVIDER:-unknown}"
            return 1
        }

        export -f provider_update_base provider_update
    fi
}

provider_load()
{
    local PROVIDER="${1:-}"
    local FILE ORIGIN MTIME

    provider_loader_validate_name "${PROVIDER}" || return 1
    FILE="$(provider_loader_path "${PROVIDER}")" || {
        provider_loader_error "Provider não encontrado: ${PROVIDER}"
        return 1
    }

    ORIGIN="$(provider_loader_origin "${FILE}")"
    MTIME="$(provider_loader_file_mtime "${FILE}")"

    provider_loader_unload
    provider_loader_progress "preparing" 12 "Carregando provider ${PROVIDER}"

    # shellcheck source=/dev/null
    source "${FILE}"

    provider_loader_validate_contract "${PROVIDER}" "${ORIGIN}" || {
        provider_loader_unload
        return 1
    }

    export DSM_ACTIVE_PROVIDER="${PROVIDER}"
    export DSM_ACTIVE_PROVIDER_FILE="${FILE}"
    export DSM_ACTIVE_PROVIDER_MTIME="${MTIME}"
    export DSM_ACTIVE_PROVIDER_ORIGIN="${ORIGIN}"

    provider_loader_wrap_progress
    provider_loader_progress "preparing" 18 "Provider ${PROVIDER} pronto"
    provider_loader_log "Provider carregado: ${PROVIDER} (${ORIGIN})"
    return 0
}

provider_require()
{
    local PROVIDER="${1:-}"
    local FILE CURRENT_MTIME

    FILE="$(provider_loader_path "${PROVIDER}" 2>/dev/null || true)"

    if [[ "${DSM_ACTIVE_PROVIDER:-}" == "${PROVIDER}" && -n "${FILE}" ]]
    then
        CURRENT_MTIME="$(provider_loader_file_mtime "${FILE}")"

        if [[ "${DSM_ACTIVE_PROVIDER_FILE:-}" == "${FILE}" && \
              "${DSM_ACTIVE_PROVIDER_MTIME:-0}" == "${CURRENT_MTIME}" ]]
        then
            provider_loader_validate_contract \
                "${PROVIDER}" "${DSM_ACTIVE_PROVIDER_ORIGIN:-builtin}"
            return $?
        fi

        provider_loader_log "Provider alterado no disco; recarregando: ${PROVIDER}"
    fi

    provider_load "${PROVIDER}"
}

provider_active()
{
    echo "${DSM_ACTIVE_PROVIDER:-}"
}

provider_list()
{
    local FILE NAME
    declare -A SEEN=()

    if [[ -d "${PROVIDER_ROOT}" ]]
    then
        for FILE in "${PROVIDER_ROOT}"/*.sh
        do
            [[ -e "${FILE}" ]] || continue
            NAME="$(basename "${FILE}" .sh)"
            SEEN["${NAME}"]=1
            echo "${NAME} builtin"
        done
    fi

    if [[ -d "${CUSTOM_PROVIDER_ROOT}" ]]
    then
        for FILE in "${CUSTOM_PROVIDER_ROOT}"/*.sh
        do
            [[ -e "${FILE}" ]] || continue
            NAME="$(basename "${FILE}" .sh)"
            [[ -n "${SEEN[${NAME}]:-}" ]] && continue
            echo "${NAME} custom"
        done
    fi
}

provider_loader_info()
{
    echo
    echo "============================================"
    echo " Capivara - Providers"
    echo "============================================"
    echo
    echo "Built-ins : ${PROVIDER_ROOT}"
    echo "Custom    : ${CUSTOM_PROVIDER_ROOT}"
    echo "Ativo     : ${DSM_ACTIVE_PROVIDER:-none}"
    echo "Origem    : ${DSM_ACTIVE_PROVIDER_ORIGIN:-none}"
    echo
    echo "Disponíveis:"
    provider_list | while read -r PROVIDER ORIGIN
    do
        echo " - ${PROVIDER} (${ORIGIN})"
    done
    echo
}

export -f provider_loader_log provider_loader_error provider_loader_progress
export -f provider_loader_http_content_length provider_loader_http_bytes_written
export -f provider_loader_http_run_with_progress provider_loader_validate_name
export -f provider_loader_path provider_loader_origin provider_loader_exists
export -f provider_loader_file_mtime provider_loader_unload
export -f provider_loader_validate_contract provider_loader_wrap_progress
export -f provider_load provider_require provider_active provider_list provider_loader_info
