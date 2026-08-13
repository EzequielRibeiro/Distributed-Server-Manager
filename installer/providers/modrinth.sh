#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
#
# Modrinth Provider
#
# Arquivo:
#   installer/providers/modrinth.sh
#
# Responsável por:
#   - pesquisar projetos no Modrinth
#   - resolver versão compatível
#   - baixar artefatos
#   - validar SHA-512/SHA-1
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

MODRINTH_API_BASE="${DSM_MODRINTH_API_BASE:-https://api.modrinth.com/v2}"
MODRINTH_USER_AGENT="${DSM_MODRINTH_USER_AGENT:-Capivara-DSM/1.0}"

DSM_PROVIDER_API_VERSION=1
DSM_PROVIDER_KIND="content"
DSM_PROVIDER_NAME="modrinth"

# -------------------------------------------------------------
# Logging
# -------------------------------------------------------------

provider_modrinth_log()
{
    echo "[DSM][MODRINTH] $*" >&2
}


provider_modrinth_error()
{
    echo "[DSM][MODRINTH][ERRO] $*" >&2
}


# -------------------------------------------------------------
# Dependencies
# -------------------------------------------------------------

provider_ensure()
{
    local MISSING=0

    for COMMAND in curl jq sha512sum sha1sum
    do
        if ! command -v "${COMMAND}" >/dev/null 2>&1
        then
            provider_modrinth_error \
                "Dependência ausente: ${COMMAND}"
            MISSING=1
        fi
    done

    (( MISSING == 0 ))
}


# -------------------------------------------------------------
# HTTP request
# -------------------------------------------------------------

modrinth_request()
{
    local URL="${1:-}"

    [[ -n "${URL}" ]] || {
        provider_modrinth_error "URL não informada."
        return 2
    }

    curl \
        --silent \
        --show-error \
        --fail \
        --location \
        --connect-timeout 15 \
        --max-time 60 \
        --header "User-Agent: ${MODRINTH_USER_AGENT}" \
        --header "Accept: application/json" \
        "${URL}"
}


# -------------------------------------------------------------
# URL encode
# -------------------------------------------------------------

modrinth_urlencode()
{
    jq -rn \
        --arg value "${1:-}" \
        '$value|@uri'
}


# -------------------------------------------------------------
# Project search
#
# Uso:
#
# provider_search QUERY GAME_VERSION LOADER TYPE [LIMIT]
#
# TYPE:
#   mod
#   plugin
#   modpack
# -------------------------------------------------------------

provider_search()
{
    local QUERY="${1:-}"
    local GAME_VERSION="${2:-}"
    local LOADER="${3:-}"
    local TYPE="${4:-mod}"
    local LIMIT="${5:-20}"

    [[ -n "${QUERY}" ]] || {
        provider_modrinth_error \
            "Termo de busca não informado."
        return 2
    }

    [[ "${LIMIT}" =~ ^[0-9]+$ ]] || LIMIT=20

    (( LIMIT > 100 )) && LIMIT=100
    (( LIMIT < 1 )) && LIMIT=1

    local FACETS
    FACETS="$(
        jq -cn \
            --arg version "${GAME_VERSION}" \
            --arg loader "${LOADER}" \
            --arg type "${TYPE}" '
            [
                (
                    if $version != ""
                    then ["versions:" + $version]
                    else empty
                    end
                ),
                (
                    if $loader != ""
                    then ["categories:" + $loader]
                    else empty
                    end
                ),
                (
                    if $type != ""
                    then ["project_type:" + $type]
                    else empty
                    end
                ),
                ["server_side:required", "server_side:optional"]
            ]
        '
    )"

    local URL
    URL="${MODRINTH_API_BASE}/search"

    URL+="?query=$(modrinth_urlencode "${QUERY}")"
    URL+="&limit=${LIMIT}"
    URL+="&index=relevance"
    URL+="&facets=$(modrinth_urlencode "${FACETS}")"

    modrinth_request "${URL}" |
        jq '
        {
            provider: "modrinth",
            total_hits: (.total_hits // 0),

            entries: [
                .hits[] |
                {
                    id: .project_id,
                    slug: .slug,
                    name: .title,
                    description: .description,
                    author: .author,

                    project_type:
                        (.project_type // null),

                    content_types:
                        (.all_project_types // []),

                    categories:
                        (.categories // []),

                    versions:
                        (.versions // []),

                    downloads:
                        (.downloads // 0),

                    icon_url:
                        (.icon_url // null),

                    license:
                        (.license // null),

                    server_side:
                        (.server_side // null),

                    client_side:
                        (.client_side // null),

                    updated_at:
                        (.date_modified // null)
                }
            ]
        }
        '
}


# -------------------------------------------------------------
# Resolve compatible version
#
# Uso:
#
# provider_resolve PROJECT GAME_VERSION LOADER
# -------------------------------------------------------------

provider_resolve()
{
    local PROJECT="${1:-}"
    local GAME_VERSION="${2:-}"
    local LOADER="${3:-}"

    [[ -n "${PROJECT}" ]] || {
        provider_modrinth_error \
            "Project ID não informado."
        return 2
    }

    [[ -n "${GAME_VERSION}" ]] || {
        provider_modrinth_error \
            "Versão do Minecraft não informada."
        return 2
    }

    [[ -n "${LOADER}" ]] || {
        provider_modrinth_error \
            "Loader não informado."
        return 2
    }

    local GAME_VERSIONS
    local LOADERS

    GAME_VERSIONS="$(
        jq -cn \
            --arg version "${GAME_VERSION}" \
            '[$version]'
    )"

    LOADERS="$(
        jq -cn \
            --arg loader "${LOADER}" \
            '[$loader]'
    )"

    local URL

    URL="${MODRINTH_API_BASE}/project/"
    URL+="$(modrinth_urlencode "${PROJECT}")"
    URL+="/version"
    URL+="?game_versions=$(modrinth_urlencode "${GAME_VERSIONS}")"
    URL+="&loaders=$(modrinth_urlencode "${LOADERS}")"
    URL+="&include_changelog=false"

    modrinth_request "${URL}" |
        jq '
        [
            .[]
            |
            select(
                .status == "listed"
                or .status == null
            )
        ]
        |
        sort_by(
            .date_published // ""
        )
        |
        reverse
        |
        .[0]
        |
        if . == null then
            {
                error:
                    "no_compatible_version"
            }
        else

            (
                [
                    .files[]
                    |
                    select(
                        .primary == true
                    )
                ][0]
                //
                .files[0]
            ) as $file

            |

            {
                provider:
                    "modrinth",

                project_id:
                    .project_id,

                version_id:
                    .id,

                version:
                    .version_number,

                version_name:
                    .name,

                version_type:
                    .version_type,

                game_versions:
                    .game_versions,

                loaders:
                    .loaders,

                dependencies:
                    (
                        .dependencies
                        // []
                    ),

                artifact:
                    {
                        provider:
                            "modrinth",

                        url:
                            $file.url,

                        filename:
                            $file.filename,

                        size:
                            $file.size,

                        sha1:
                            (
                                $file.hashes.sha1
                                // null
                            ),

                        sha512:
                            (
                                $file.hashes.sha512
                                // null
                            )
                    }
            }

        end
        '
}


# -------------------------------------------------------------
# Installation
#
# PACKAGE_ID pode ser:
#
#   URL direta do CDN Modrinth
#
# O nome real do arquivo pode ser informado através de:
#
#   DSM_CONTENT_FILENAME
# -------------------------------------------------------------

provider_install()
{
    local PACKAGE_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local INSTALL_USER="${3:-anonymous}"

    : "${INSTALL_USER}"

    [[ -n "${PACKAGE_ID}" ]] || {
        provider_modrinth_error \
            "Artefato não informado."
        return 2
    }

    [[ -n "${INSTALL_PATH}" ]] || {
        provider_modrinth_error \
            "Destino não informado."
        return 2
    }

    case "${PACKAGE_ID}" in

        https://cdn.modrinth.com/*)
            ;;

        *)
            provider_modrinth_error \
                "URL Modrinth inválida."
            return 1
            ;;

    esac

    local FILENAME="${DSM_CONTENT_FILENAME:-}"

    if [[ -z "${FILENAME}" ]]
    then
        FILENAME="$(
            basename \
                "${PACKAGE_ID%%\?*}"
        )"
    fi

    [[ -n "${FILENAME}" ]] || {
        provider_modrinth_error \
            "Não foi possível determinar o nome do arquivo."
        return 1
    }

    case "${FILENAME}" in
        */*|*\\*)
            provider_modrinth_error \
                "Nome de arquivo inseguro."
            return 1
            ;;
    esac

    mkdir -p "${INSTALL_PATH}"

    local DESTINATION
    DESTINATION="${INSTALL_PATH}/${FILENAME}"

    local TEMPORARY
    TEMPORARY="${DESTINATION}.part.$$"

    rm -f -- "${TEMPORARY}"

    provider_modrinth_log \
        "Baixando ${FILENAME}"

    if ! curl \
        --fail \
        --location \
        --show-error \
        --connect-timeout 20 \
        --retry 3 \
        --retry-delay 2 \
        --header "User-Agent: ${MODRINTH_USER_AGENT}" \
        --output "${TEMPORARY}" \
        "${PACKAGE_ID}"
    then
        rm -f -- "${TEMPORARY}"
        return 1
    fi

    [[ -s "${TEMPORARY}" ]] || {
        rm -f -- "${TEMPORARY}"

        provider_modrinth_error \
            "Download vazio."

        return 1
    }

    # ---------------------------------------------------------
    # SHA-512
    # ---------------------------------------------------------

    if [[ -n "${DSM_CONTENT_SHA512:-}" ]]
    then
        local ACTUAL_SHA512

        ACTUAL_SHA512="$(
            sha512sum "${TEMPORARY}" |
            awk '{print $1}'
        )"

        if [[ "${ACTUAL_SHA512,,}" != "${DSM_CONTENT_SHA512,,}" ]]; then
            rm -f -- "${TEMPORARY}"

            provider_modrinth_error \
                "SHA-512 do artefato não corresponde."

            return 1
        fi
    fi

    # ---------------------------------------------------------
    # SHA-1 fallback
    # ---------------------------------------------------------

    if [[ -z "${DSM_CONTENT_SHA512:-}" && -n "${DSM_CONTENT_SHA1:-}" ]]; then
        local ACTUAL_SHA1

        ACTUAL_SHA1="$(
            sha1sum "${TEMPORARY}" |
            awk '{print $1}'
        )"

        if [[ "${ACTUAL_SHA1,,}" != "${DSM_CONTENT_SHA1,,}" ]]; then
            rm -f -- "${TEMPORARY}"

            provider_modrinth_error \
                "SHA-1 do artefato não corresponde."

            return 1
        fi
    fi

    mv -- \
        "${TEMPORARY}" \
        "${DESTINATION}"

    provider_modrinth_log \
        "Artefato instalado: ${DESTINATION}"
}


provider_verify()
{
    local INSTALL_PATH="${1:-}"

    [[ -e "${INSTALL_PATH}" ]]
}


provider_version()
{
    printf '%s\n' \
        "${DSM_CONTENT_VERSION:-unknown}"
}


provider_info()
{
    jq -n '
    {
        name: "modrinth",
        kind: "content",
        api_version: 1,
        capabilities: [
            "search",
            "resolve",
            "download",
            "sha512",
            "sha1"
        ]
    }
    '
}