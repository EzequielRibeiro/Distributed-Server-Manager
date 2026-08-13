#!/usr/bin/env bash
# =============================================================
# Capivara Dashboard API
# Catalog / Content Provider Adapter
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

CATALOG="${DSM_ROOT}/installer/catalog.sh"
PROVIDER_LOADER="${DSM_ROOT}/installer/provider_loader.sh"

CATALOG_V2_ROOT="${DSM_ROOT}/catalog/v2"
RUNTIMES_ROOT="${CATALOG_V2_ROOT}/runtimes"

ACTION="${1:-list}"
shift || true

# =============================================================
# Catalog v2 compatibility
#
# O Dashboard usa ações HTTP simplificadas enquanto o
# installer/catalog.sh usa a hierarquia:
#
#   content list
#   content show
#   content list-installed
#
# Este adaptador mantém a API web estável sem duplicar a
# implementação do Catalog v2.
# =============================================================

case "${ACTION}" in
    content)
        exec "${CATALOG}"             content list "${1:-}" --json
        ;;

    content-definition)
        [[ -n "${1:-}" ]] || {
            printf '{"error":"missing_content_id"}\n'
            exit 2
        }

        exec "${CATALOG}"             content show "${1}" --json
        ;;

    installed)
        [[ -n "${1:-}" ]] || {
            printf '{"error":"missing_instance_path"}\n'
            exit 2
        }

        exec "${CATALOG}"             content list-installed "${1}" --json
        ;;
esac


json_error()
{
    local CODE="${1:-catalog_error}"
    local MESSAGE="${2:-Erro no catálogo.}"

    jq -nc \
        --arg error "${CODE}" \
        --arg message "${MESSAGE}" \
        '{
            error: $error,
            message: $message
        }'
}


# =============================================================
# Runtime helpers
# =============================================================

runtime_file_by_id()
{
    local RUNTIME_ID="${1:-}"

    if [[ -z "${RUNTIME_ID}" ]]
    then
        return 1
    fi

    local FILE

    while IFS= read -r FILE
    do
        if jq -e \
            --arg id "${RUNTIME_ID}" \
            '.id == $id' \
            "${FILE}" \
            >/dev/null 2>&1
        then
            printf '%s\n' "${FILE}"
            return 0
        fi
    done < <(
        find "${RUNTIMES_ROOT}" \
            -type f \
            -name '*.json' \
            -print 2>/dev/null |
        sort
    )

    return 1
}


catalog_runtimes()
{
    local GAME="${1:-}"

    if [[ -n "${GAME}" ]]
    then
        local DIRECTORY="${RUNTIMES_ROOT}/${GAME}"

        if [[ ! -d "${DIRECTORY}" ]]
        then
            printf '[]\n'
            return 0
        fi

        find "${DIRECTORY}" \
            -maxdepth 1 \
            -type f \
            -name '*.json' \
            -print0 |
        sort -z |
        xargs -0 -r jq -s '.'
        return
    fi

    find "${RUNTIMES_ROOT}" \
        -type f \
        -name '*.json' \
        -print0 |
    sort -z |
    xargs -0 -r jq -s '.'
}


catalog_runtime()
{
    local RUNTIME_ID="${1:-}"

    if [[ -z "${RUNTIME_ID}" ]]
    then
        json_error \
            "missing_runtime_id" \
            "Informe o ID do runtime."
        return 2
    fi

    local FILE

    if ! FILE="$(
        runtime_file_by_id "${RUNTIME_ID}"
    )"
    then
        json_error \
            "runtime_not_found" \
            "Runtime não encontrado: ${RUNTIME_ID}"
        return 2
    fi

    jq '.' "${FILE}"
}


# =============================================================
# PaperMC
# =============================================================

papermc_versions()
{
    local RUNTIME_FILE="${1:?runtime file required}"

    local API_BASE
    local PROJECT

    API_BASE="$(
        jq -r \
            '.version.config.api_base // "https://fill.papermc.io/v3"' \
            "${RUNTIME_FILE}"
    )"

    PROJECT="$(
        jq -r \
            '.version.config.project // "paper"' \
            "${RUNTIME_FILE}"
    )"

    local RESPONSE

    RESPONSE="$(
        curl \
            -fsSL \
            --connect-timeout 10 \
            --max-time 30 \
            "${API_BASE}/projects/${PROJECT}"
    )" || {
        json_error \
            "resolver_request_failed" \
            "Não foi possível consultar as versões do PaperMC."
        return 1
    }


    #  A API do Paper pode evoluir no formato.
    #  Tentamos aceitar tanto um array direto quanto
    #  grupos de versões.

    jq -c '
        def flatten_versions:
            if (.versions | type) == "array" then
                .versions
            elif (.versions | type) == "object" then
                [
                    .versions[]
                    | if type == "array"
                      then .[]
                      else .
                      end
                ]
            else
                []
            end;

        flatten_versions
        | unique
        | sort
        | reverse
        | map({
            value: tostring,
            label: tostring
        })
        | if length > 0
          then .[0].recommended = true | .
          else .
          end
    ' <<<"${RESPONSE}"
}


papermc_builds()
{
    local RUNTIME_FILE="${1:?runtime file required}"
    local VERSION="${2:-}"

    if [[ -z "${VERSION}" ]]
    then
        json_error \
            "missing_version" \
            "Informe a versão do Minecraft."
        return 2
    fi

    local API_BASE
    local PROJECT

    API_BASE="$(
        jq -r \
            '.version.config.api_base // "https://fill.papermc.io/v3"' \
            "${RUNTIME_FILE}"
    )"

    PROJECT="$(
        jq -r \
            '.version.config.project // "paper"' \
            "${RUNTIME_FILE}"
    )"

    local RESPONSE

    RESPONSE="$(
        curl \
            -fsSL \
            --connect-timeout 10 \
            --max-time 30 \
            "${API_BASE}/projects/${PROJECT}/versions/${VERSION}/builds"
    )" || {
        json_error \
            "resolver_request_failed" \
            "Não foi possível consultar as builds do PaperMC."
        return 1
    }

    jq -c '
        (
            if type == "array" then
                .
            elif (.builds | type) == "array" then
                .builds
            else
                []
            end
        )
        |
        map(
            . as $raw
            |
            (
                .id
                // .build
                // .number
                // .build_number
            ) as $number
            |
            {
                value: ($number | tostring),
                label: ("Build " + ($number | tostring)),
                channel: (.channel // null),
                raw: $raw
            }
        )
        |
        sort_by(.value | tonumber)
        |
        reverse
        |
        if length > 0
        then .[0].recommended = true
        else .
        end
    ' <<<"${RESPONSE}"

}


# =============================================================
# Fabric Meta
# =============================================================

fabric_versions()
{
    local RUNTIME_FILE="${1:?runtime file required}"

    local API_BASE

    API_BASE="$(
        jq -r \
            '.version.config.api_base // "https://meta.fabricmc.net/v2"' \
            "${RUNTIME_FILE}"
    )"

    local RESPONSE

    RESPONSE="$(
        curl \
            -fsSL \
            --connect-timeout 10 \
            --max-time 30 \
            "${API_BASE}/versions/game"
    )" || {
        json_error \
            "resolver_request_failed" \
            "Não foi possível consultar as versões do Fabric."
        return 1
    }

    jq -c '
        map(
            select(.stable == true)
            | {
                value: (.version | tostring),
                label: (.version | tostring),
                recommended: false,
                raw: .
            }
        )
        | if length > 0
          then .[0].recommended = true | .
          else .
          end
    ' <<<"${RESPONSE}"
}


fabric_builds()
{
    local RUNTIME_FILE="${1:?runtime file required}"
    local VERSION="${2:-}"

    if [[ -z "${VERSION}" ]]
    then
        json_error \
            "missing_version" \
            "Informe a versão do Minecraft."
        return 2
    fi

    local API_BASE

    API_BASE="$(
        jq -r \
            '.version.config.api_base // "https://meta.fabricmc.net/v2"' \
            "${RUNTIME_FILE}"
    )"

    local RESPONSE

    RESPONSE="$(
        curl \
            -fsSL \
            --connect-timeout 10 \
            --max-time 30 \
            "${API_BASE}/versions/loader/${VERSION}"
    )" || {
        json_error \
            "resolver_request_failed" \
            "Não foi possível consultar os loaders do Fabric."
        return 1
    }

    jq -c '
        map({
            value:
                (
                    .loader.version
                    // .version
                    // .loader
                    | tostring
                ),

            label:
                (
                    "Loader "
                    +
                    (
                        .loader.version
                        // .version
                        // .loader
                        | tostring
                    )
                ),

            recommended:
                (
                    .loader.stable
                    // .stable
                    // false
                ),

            raw: .
        })
        | if length > 0 and
             (map(select(.recommended == true)) | length) == 0
          then .[0].recommended = true | .
          else .
          end
    ' <<<"${RESPONSE}"
}


# =============================================================
# Arclight / GitHub Releases
# =============================================================

arclight_versions()
{
    local RUNTIME_FILE="${1:?runtime file required}"

    local REPOSITORY
    local LIMIT

    REPOSITORY="$(
        jq -r \
            '.version.config.repository // .artifact.repository // empty' \
            "${RUNTIME_FILE}"
    )"

    LIMIT="$(
        jq -r \
            '.version.config.discovery_limit // 50' \
            "${RUNTIME_FILE}"
    )"

    if [[ -z "${REPOSITORY}" ]]
    then
        json_error \
            "resolver_configuration_error" \
            "Repositório GitHub do Arclight não configurado."
        return 1
    fi

    local RESPONSE

    RESPONSE="$(
        curl \
            -fsSL \
            --connect-timeout 10 \
            --max-time 30 \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/${REPOSITORY}/releases?per_page=${LIMIT}"
    )" || {
        json_error \
            "resolver_request_failed" \
            "Não foi possível consultar as releases do Arclight."
        return 1
    }

    jq -c '
        [
            .[]
            | .assets[]?
            | .name
            | capture(
                "arclight-(?:fabric|forge|neoforge)-(?<version>1\\.[0-9]+(?:\\.[0-9]+)?)-"
            )?
            | .version
        ]
        | map(select(. != null))
        | unique
        | sort
        | reverse
        | map({
            value: .,
            label: .
        })
        | if length > 0
          then .[0].recommended = true | .
          else .
          end
    ' <<<"${RESPONSE}"
}


arclight_builds()
{
    local RUNTIME_FILE="${1:?runtime file required}"
    local VERSION="${2:-}"

    if [[ -z "${VERSION}" ]]
    then
        json_error \
            "missing_version" \
            "Informe a versão do Minecraft."
        return 2
    fi

    local REPOSITORY
    local LIMIT

    REPOSITORY="$(
        jq -r \
            '.version.config.repository // .artifact.repository // empty' \
            "${RUNTIME_FILE}"
    )"

    LIMIT="$(
        jq -r \
            '.version.config.discovery_limit // 50' \
            "${RUNTIME_FILE}"
    )"

    local RESPONSE

    RESPONSE="$(
        curl \
            -fsSL \
            --connect-timeout 10 \
            --max-time 30 \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/${REPOSITORY}/releases?per_page=${LIMIT}"
    )" || {
        json_error \
            "resolver_request_failed" \
            "Não foi possível consultar as builds do Arclight."
        return 1
    }

    jq -c \
        --arg version "${VERSION}" '
        [
            .[]
            | . as $release
            | .assets[]?
            | select(
                (.name | test(
                    "arclight-(fabric|forge|neoforge)-"
                    + ($version | gsub("\\."; "\\."))
                    + "-"
                ))
            )
            | {
                value:
                    (
                        (.id // .name)
                        | tostring
                    ),

                label:
                    .name,

                download_url:
                    .browser_download_url,

                release:
                    $release.tag_name,

                raw:
                    .
            }
        ]
        | if length > 0
          then .[0].recommended = true | .
          else .
          end
    ' <<<"${RESPONSE}"
}


# =============================================================
# Minecraft Bedrock
# =============================================================

bedrock_versions()
{
    local RUNTIME_FILE="${1:?runtime file required}"

    local PAGE

    PAGE="$(
        jq -r \
            '.version.config.download_page // empty' \
            "${RUNTIME_FILE}"
    )"

    if [[ -z "${PAGE}" ]]
    then
        json_error \
            "resolver_configuration_error" \
            "Página de download do Bedrock não configurada."
        return 1
    fi

    local HTML

    HTML="$(
        curl \
            -fsSL \
            --connect-timeout 10 \
            --max-time 30 \
            "${PAGE}"
    )" || {
        json_error \
            "resolver_request_failed" \
            "Não foi possível consultar o Minecraft Bedrock."
        return 1
    }

    local URL

    URL="$(
        grep -oE \
            'https://[^"[:space:]]*bedrock-server-[0-9.]+\.zip' \
            <<<"${HTML}" |
        head -n 1
    )"

    if [[ -z "${URL}" ]]
    then
        json_error \
            "resolver_parse_failed" \
            "Não foi possível identificar a versão atual do Bedrock."
        return 1
    fi

    local VERSION

    VERSION="$(
        sed -nE \
            's/.*bedrock-server-([0-9.]+)\.zip.*/\1/p' \
            <<<"${URL}"
    )"

    jq -nc \
        --arg version "${VERSION}" \
        --arg url "${URL}" \
        '[
            {
                value: $version,
                label: $version,
                recommended: true,
                raw: {
                    download_url: $url
                }
            }
        ]'
}


bedrock_builds()
{
    local VERSION="${2:-}"

    if [[ -z "${VERSION}" ]]
    then
        json_error \
            "missing_version" \
            "Informe a versão do Bedrock."
        return 2
    fi

    jq -nc \
        --arg version "${VERSION}" \
        '[
            {
                value: "current",
                label: ("Build oficial " + $version),
                recommended: true
            }
        ]'
}


# =============================================================
# Resolução genérica
# =============================================================

catalog_versions()
{
    local RUNTIME_ID="${1:-}"

    if [[ -z "${RUNTIME_ID}" ]]
    then
        json_error \
            "missing_runtime_id" \
            "Informe o runtime."
        return 2
    fi

    local FILE

    if ! FILE="$(
        runtime_file_by_id "${RUNTIME_ID}"
    )"
    then
        json_error \
            "runtime_not_found" \
            "Runtime não encontrado: ${RUNTIME_ID}"
        return 2
    fi

    local STRATEGY
    local RESOLVER

    STRATEGY="$(
        jq -r \
            '.version.strategy // "static"' \
            "${FILE}"
    )"

    RESOLVER="$(
        jq -r \
            '.version.resolver // empty' \
            "${FILE}"
    )"

    if [[ "${STRATEGY}" == "static" ]]
    then
        jq -c '
            [
                {
                    value:
                        (
                            .version.value
                            // .version.version
                            // "current"
                            | tostring
                        ),

                    label:
                        (
                            .version.value
                            // .version.version
                            // "Versão atual / recomendada"
                            | tostring
                        ),

                    recommended: true,

                    raw: .version
                }
            ]
        ' "${FILE}"

        return
    fi

    case "${RESOLVER}" in
        papermc)
            papermc_versions "${FILE}"
            ;;

        fabric_meta)
            fabric_versions "${FILE}"
            ;;

        github_releases)
            arclight_versions "${FILE}"
            ;;

        minecraft_bedrock)
            bedrock_versions "${FILE}"
            ;;

        *)
            json_error \
                "unsupported_version_resolver" \
                "Resolver de versão não suportado: ${RESOLVER}"
            return 2
            ;;
    esac
}


catalog_builds()
{
    local RUNTIME_ID="${1:-}"
    local VERSION="${2:-}"

    if [[ -z "${RUNTIME_ID}" ]]
    then
        json_error \
            "missing_runtime_id" \
            "Informe o runtime."
        return 2
    fi

    local FILE

    if ! FILE="$(
        runtime_file_by_id "${RUNTIME_ID}"
    )"
    then
        json_error \
            "runtime_not_found" \
            "Runtime não encontrado: ${RUNTIME_ID}"
        return 2
    fi

    local STRATEGY
    local RESOLVER

    STRATEGY="$(
        jq -r \
            '.version.strategy // "static"' \
            "${FILE}"
    )"

    RESOLVER="$(
        jq -r \
            '.version.resolver // empty' \
            "${FILE}"
    )"

    if [[ "${STRATEGY}" == "static" ]]
    then
        local BUILD

        BUILD="$(
            jq -r \
                '.version.build // empty' \
                "${FILE}"
        )"

        if [[ -n "${BUILD}" ]]
        then
            jq -nc \
                --arg build "${BUILD}" \
                '[
                    {
                        value: $build,
                        label: "Build recomendada",
                        recommended: true
                    }
                ]'
        else
            jq -nc '
                [
                    {
                        value: "current",
                        label: "Build atual / recomendada",
                        recommended: true
                    }
                ]
            '
        fi

        return
    fi

    case "${RESOLVER}" in
        papermc)
            papermc_builds \
                "${FILE}" \
                "${VERSION}"
            ;;

        fabric_meta)
            fabric_builds \
                "${FILE}" \
                "${VERSION}"
            ;;

        github_releases)
            arclight_builds \
                "${FILE}" \
                "${VERSION}"
            ;;

        minecraft_bedrock)
            bedrock_builds \
                "${FILE}" \
                "${VERSION}"
            ;;

        *)
            json_error \
                "unsupported_build_resolver" \
                "Resolver de build não suportado: ${RESOLVER}"
            return 2
            ;;
    esac
}


# =============================================================
# Busca externa
# =============================================================

catalog_search()
{
    local PROVIDER="${1:-modrinth}"
    local QUERY="${2:-}"
    local GAME="${3:-minecraft}"
    local GAME_VERSION="${4:-}"
    local LOADER="${5:-}"
    local CONTENT_TYPE="${6:-mod}"
    local LIMIT="${7:-20}"

    if [[ "${PROVIDER}" != "modrinth" ]]
    then
        json_error \
            "unsupported_search_provider" \
            "Provider de busca não suportado: ${PROVIDER}"
        return 2
    fi

    if [[ -z "${QUERY}" ]]
    then
        json_error \
            "missing_query" \
            "Informe um termo de busca."
        return 2
    fi

    if [[ "${GAME}" != "minecraft" ]]
    then
        json_error \
            "unsupported_game" \
            "A busca Modrinth está disponível inicialmente para Minecraft."
        return 2
    fi

    if [[ ! -f "${PROVIDER_LOADER}" ]]
    then
        json_error \
            "provider_loader_missing" \
            "Provider Loader não encontrado."
        return 1
    fi

    # shellcheck source=/dev/null
    source "${PROVIDER_LOADER}"

    if ! provider_require "${PROVIDER}"
    then
        json_error \
            "provider_unavailable" \
            "Provider ${PROVIDER} não disponível."
        return 1
    fi

    if ! declare -F \
        provider_search \
        >/dev/null 2>&1
    then
        json_error \
            "provider_search_unsupported" \
            "Provider não implementa busca."
        return 1
    fi

    provider_search \
        "${QUERY}" \
        "${GAME_VERSION}" \
        "${LOADER}" \
        "${CONTENT_TYPE}" \
        "${LIMIT}"
}


# =============================================================
# Ações
# =============================================================

case "${ACTION}" in

    # ---------------------------------------------------------
    # Compatibilidade
    # ---------------------------------------------------------

    compatibility)
        [[ -n "${1:-}" ]] || {
            printf '{"error":"missing_compatibility_request"}\n'
            exit 2
        }

        exec "${CATALOG}"             compatibility check "$1" --json
        ;;

    # ---------------------------------------------------------
    # Catálogo V2
    # ---------------------------------------------------------

    runtimes)
        catalog_runtimes "$@"
        ;;

    runtime)
        catalog_runtime "$@"
        ;;

    versions)
        catalog_versions "$@"
        ;;

    builds)
        catalog_builds "$@"
        ;;


    # ---------------------------------------------------------
    # Catálogo legado
    # ---------------------------------------------------------

    list|editions|variants|versions-legacy|resolve|prepare)
        LEGACY_ACTION="${ACTION}"

        if [[ "${ACTION}" == "versions-legacy" ]]
        then
            LEGACY_ACTION="versions"
        fi

        exec \
            "${CATALOG}" \
            "${LEGACY_ACTION}" \
            "$@"
        ;;


    # ---------------------------------------------------------
    # Busca externa
    # ---------------------------------------------------------

    search)
        catalog_search "$@"
        ;;


    # ---------------------------------------------------------
    # Inválida
    # ---------------------------------------------------------

    *)
        jq -nc \
            --arg action "${ACTION}" \
            '{
                error:
                    "invalid_catalog_action",

                action:
                    $action,

                actions: [
                    "runtimes",
                    "runtime",
                    "versions",
                    "builds",
                    "search",
                    "list",
                    "editions",
                    "variants",
                    "resolve",
                    "prepare"
                ]
            }'

        exit 2
        ;;
esac