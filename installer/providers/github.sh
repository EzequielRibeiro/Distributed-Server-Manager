#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Installation Provider - GitHub Releases
#
# PACKAGE_ID esperado: owner/repository
# Variáveis opcionais:
#   DSM_GITHUB_TAG=latest|v1.2.3
#   DSM_GITHUB_ASSET=nome-exato-ou-glob
#   DSM_GITHUB_TOKEN=<token>
#   DSM_GITHUB_SHA256=<sha256 esperado>
#   DSM_GITHUB_EXECUTABLE=1|0
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "${DSM_ROOT}/installer/provider_progress.sh"

GITHUB_PROVIDER_REPOSITORY=""
GITHUB_PROVIDER_TAG=""
GITHUB_PROVIDER_ASSET=""
GITHUB_PROVIDER_URL=""
GITHUB_PROVIDER_SHA256=""

github_log()
{
    echo "[DSM][GITHUB] $*"
}

github_error()
{
    echo "[DSM][GITHUB][ERRO] $*" >&2
}

github_provider_ensure()
{
    command -v curl >/dev/null 2>&1 || {
        github_error "curl não disponível."
        return 1
    }

    command -v jq >/dev/null 2>&1 || {
        github_error "jq não disponível."
        return 1
    }

    return 0
}

github_provider_validate_repository()
{
    local REPO="${1:-}"
    [[ "${REPO}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
}

github_api_headers()
{
    local TOKEN="${DSM_GITHUB_TOKEN:-}"

    printf '%s\n' \
        "Accept: application/vnd.github+json" \
        "X-GitHub-Api-Version: 2022-11-28"

    if [[ -n "${TOKEN}" ]]
    then
        printf '%s\n' "Authorization: Bearer ${TOKEN}"
    fi
}

github_api_get()
{
    local URL="$1"
    local ARGS=(--fail --silent --show-error --location)
    local HEADER

    while IFS= read -r HEADER
    do
        [[ -n "${HEADER}" ]] && ARGS+=(--header "${HEADER}")
    done < <(github_api_headers)

    curl "${ARGS[@]}" "${URL}"
}

github_release_json()
{
    local REPO="$1"
    local TAG="${2:-latest}"
    local API

    if [[ "${TAG}" == "latest" || -z "${TAG}" ]]
    then
        API="https://api.github.com/repos/${REPO}/releases/latest"
    else
        API="https://api.github.com/repos/${REPO}/releases/tags/${TAG}"
    fi

    github_api_get "${API}"
}

github_asset_select()
{
    local JSON="$1"
    local PATTERN="${2:-}"

    if [[ -z "${PATTERN}" ]]
    then
        jq -c '.assets[0] // empty' <<< "${JSON}"
        return
    fi

    local EXACT
    EXACT="$(jq -c --arg p "${PATTERN}" '.assets[] | select(.name == $p)' <<< "${JSON}" | head -n1)"
    if [[ -n "${EXACT}" ]]
    then
        printf '%s\n' "${EXACT}"
        return
    fi

    local REGEX
    REGEX="$(printf '%s' "${PATTERN}" | sed -e 's/[.[\^$+?(){}|]/\\&/g' -e 's/\*/.*/g')"
    jq -c --arg r "^${REGEX}$" '.assets[] | select(.name | test($r))' <<< "${JSON}" | head -n1
}

github_content_length()
{
    local URL="$1"
    local TOKEN="${DSM_GITHUB_TOKEN:-}"
    local ARGS=(--head --silent --show-error --location)

    [[ -n "${TOKEN}" ]] && ARGS+=(--header "Authorization: Bearer ${TOKEN}")

    curl "${ARGS[@]}" "${URL}" 2>/dev/null |
        awk 'BEGIN{IGNORECASE=1} /^content-length:/ {gsub("\r", "", $2); n=$2} END{print n+0}'
}

github_download_asset()
{
    local URL="$1"
    local DESTINATION="$2"
    local TOTAL="${3:-0}"
    local TOKEN="${DSM_GITHUB_TOKEN:-}"
    local ARGS=(--fail --location --retry 3 --connect-timeout 30 --output "${DESTINATION}")

    [[ -n "${TOKEN}" ]] && ARGS+=(--header "Authorization: Bearer ${TOKEN}")

    mkdir -p "$(dirname "${DESTINATION}")"
    rm -f "${DESTINATION}"

    provider_progress_publish "downloading" 25 "GitHub Releases: iniciando download"

    curl "${ARGS[@]}" "${URL}" &
    local PID=$!

    local MONITOR_PID=""
    if [[ "${TOTAL}" =~ ^[0-9]+$ ]] && (( TOTAL > 0 ))
    then
        provider_progress_monitor_file \
            "${PID}" \
            "${DESTINATION}" \
            "${TOTAL}" \
            "GitHub Releases" \
            25 \
            75 &
        MONITOR_PID=$!
    fi

    wait "${PID}"
    local STATUS=$?

    if [[ -n "${MONITOR_PID}" ]]
    then
        wait "${MONITOR_PID}" 2>/dev/null || true
    fi

    if (( STATUS != 0 ))
    then
        rm -f "${DESTINATION}"
        return "${STATUS}"
    fi

    [[ -s "${DESTINATION}" ]] || return 1

    provider_progress_publish "downloaded" 75 "GitHub Releases: download concluído"
    return 0
}

github_provider_sha256()
{
    sha256sum "$1" | awk '{print $1}'
}

github_provider_write_metadata()
{
    local INSTALL_PATH="$1"
    local REPO="$2"
    local TAG="$3"
    local ASSET="$4"
    local URL="$5"
    local SHA256="${6:-}"

    mkdir -p "${INSTALL_PATH}/.dsm"
    {
        printf 'PROVIDER=%q\n' "github"
        printf 'REPOSITORY=%q\n' "${REPO}"
        printf 'TAG=%q\n' "${TAG}"
        printf 'ASSET=%q\n' "${ASSET}"
        printf 'URL=%q\n' "${URL}"
        printf 'SHA256=%q\n' "${SHA256}"
    } > "${INSTALL_PATH}/.dsm/github-provider.conf"
}

github_provider_read_metadata()
{
    local FILE="$1/.dsm/github-provider.conf"
    [[ -f "${FILE}" ]] || return 1

    source "${FILE}"

    GITHUB_PROVIDER_REPOSITORY="${REPOSITORY:-}"
    GITHUB_PROVIDER_TAG="${TAG:-}"
    GITHUB_PROVIDER_ASSET="${ASSET:-}"
    GITHUB_PROVIDER_URL="${URL:-}"
    GITHUB_PROVIDER_SHA256="${SHA256:-}"
}

github_provider_install()
{
    local REPO="${1:-}"
    local INSTALL_PATH="${2:-}"
    local AUTH="${3:-}"
    local TAG="${DSM_GITHUB_TAG:-latest}"
    local ASSET_PATTERN="${DSM_GITHUB_ASSET:-}"
    local EXPECTED_SHA256="${DSM_GITHUB_SHA256:-}"

    local RELEASE ASSET NAME URL TOTAL DESTINATION ACTUAL_SHA256 RESOLVED_TAG

    github_provider_ensure || return 1

    if ! github_provider_validate_repository "${REPO}"
    then
        github_error "PACKAGE_ID inválido. Use owner/repository."
        return 1
    fi

    provider_progress_publish "preparing" 20 "Consultando GitHub Releases"

    RELEASE="$(github_release_json "${REPO}" "${TAG}")" || return 1
    RESOLVED_TAG="$(jq -r '.tag_name // empty' <<< "${RELEASE}")"

    ASSET="$(github_asset_select "${RELEASE}" "${ASSET_PATTERN}")"
    if [[ -z "${ASSET}" ]]
    then
        github_error "Nenhum asset compatível encontrado."
        return 1
    fi

    NAME="$(jq -r '.name' <<< "${ASSET}")"
    URL="$(jq -r '.browser_download_url' <<< "${ASSET}")"
    TOTAL="$(jq -r '.size // 0' <<< "${ASSET}")"
    DESTINATION="${INSTALL_PATH}/${NAME}"

    github_log "Repositório : ${REPO}"
    github_log "Release     : ${RESOLVED_TAG:-${TAG}}"
    github_log "Asset       : ${NAME}"
    github_log "Destino     : ${DESTINATION}"

    if ! github_download_asset "${URL}" "${DESTINATION}" "${TOTAL}"
    then
        github_error "Falha ao baixar asset."
        return 1
    fi

    if [[ -n "${EXPECTED_SHA256}" ]]
    then
        provider_progress_publish "validating" 76 "Validando SHA256 do asset"
        ACTUAL_SHA256="$(github_provider_sha256 "${DESTINATION}")" || return 1

        if [[ "${ACTUAL_SHA256,,}" != "${EXPECTED_SHA256,,}" ]]
        then
            github_error "SHA256 inválido."
            rm -f "${DESTINATION}"
            return 1
        fi
    else
        ACTUAL_SHA256="$(github_provider_sha256 "${DESTINATION}" 2>/dev/null || true)"
    fi

    # O Atomic Engine publica explicitamente DSM_EXPECTED_EXECUTABLE
    # durante provider_install(). Isso evita depender de escopo dinâmico
    # ou de flags específicas do provider para satisfazer o contrato de
    # executável esperado pelo Integrity Engine.
    if [[ "${DSM_GITHUB_EXECUTABLE:-0}" == "1" || ( -n "${DSM_EXPECTED_EXECUTABLE:-}" && "${NAME}" == "${DSM_EXPECTED_EXECUTABLE}" ) ]]
    then
        provider_progress_publish "installing" 77 "Aplicando permissão de execução ao asset"
        chmod +x "${DESTINATION}" || {
            github_error "Não foi possível tornar o asset executável."
            return 1
        }

        if [[ ! -x "${DESTINATION}" ]]
        then
            github_error "Asset continua sem permissão de execução após chmod: ${DESTINATION}"
            return 1
        fi
    fi

    github_provider_write_metadata \
        "${INSTALL_PATH}" \
        "${REPO}" \
        "${RESOLVED_TAG:-${TAG}}" \
        "${NAME}" \
        "${URL}" \
        "${ACTUAL_SHA256}"

    github_log "GitHub Release instalada."
    return 0
}

github_provider_update()
{
    github_provider_install "$@"
}

github_provider_verify()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local EXECUTABLE="${3:-}"

    github_provider_read_metadata "${INSTALL_PATH}" || return 1

    local FILE="${INSTALL_PATH}/${GITHUB_PROVIDER_ASSET}"
    [[ -f "${FILE}" ]] || return 1

    if [[ -n "${GITHUB_PROVIDER_SHA256}" ]]
    then
        local ACTUAL
        ACTUAL="$(github_provider_sha256 "${FILE}")" || return 1
        [[ "${ACTUAL,,}" == "${GITHUB_PROVIDER_SHA256,,}" ]] || return 1
    fi

    if [[ -n "${EXECUTABLE}" ]]
    then
        local EXEC_PATH="${INSTALL_PATH}/${EXECUTABLE}"
        [[ -x "${EXEC_PATH}" ]] || return 1
    fi

    return 0
}

github_provider_info()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    if ! github_provider_read_metadata "${INSTALL_PATH}"
    then
        echo "provider=github"
        echo "repository=${PACKAGE_ID}"
        echo "version=unknown"
        return 1
    fi

    echo "provider=github"
    echo "repository=${GITHUB_PROVIDER_REPOSITORY}"
    echo "tag=${GITHUB_PROVIDER_TAG}"
    echo "asset=${GITHUB_PROVIDER_ASSET}"
    echo "version=${GITHUB_PROVIDER_TAG:-unknown}"
}

github_provider_version()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"

    if github_provider_read_metadata "${INSTALL_PATH}"
    then
        echo "${GITHUB_PROVIDER_TAG:-unknown}"
    else
        echo "unknown"
        return 1
    fi
}

provider_ensure()
{
    github_provider_ensure
}

provider_install()
{
    github_provider_install "$@"
}

provider_update()
{
    github_provider_update "$@"
}

provider_verify()
{
    github_provider_verify "$@"
}

provider_info()
{
    github_provider_info "$@"
}

provider_version()
{
    github_provider_version "$@"
}

export -f github_log
export -f github_error
export -f github_provider_ensure
export -f github_provider_validate_repository
export -f github_api_headers
export -f github_api_get
export -f github_release_json
export -f github_asset_select
export -f github_content_length
export -f github_download_asset
export -f github_provider_sha256
export -f github_provider_write_metadata
export -f github_provider_read_metadata
export -f github_provider_install
export -f github_provider_update
export -f github_provider_verify
export -f github_provider_info
export -f github_provider_version
export -f provider_ensure
export -f provider_install
export -f provider_update
export -f provider_verify
export -f provider_info
export -f provider_version
