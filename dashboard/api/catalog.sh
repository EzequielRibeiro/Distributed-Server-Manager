#!/usr/bin/env bash
# =============================================================
# Capivara Dashboard API
# Catalog / Content Provider Adapter
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
CATALOG="${DSM_ROOT}/installer/catalog.sh"
PROVIDER_LOADER="${DSM_ROOT}/installer/provider_loader.sh"
RESOLVER_ROOT="${DSM_ROOT}/installer/version_resolvers"
CATALOG_V2_ROOT="${DSM_ROOT}/catalog/v2"
CATALOG_ROOT="${CATALOG_V2_ROOT}"
CATALOG_PATHS="${DSM_ROOT}/installer/catalog_paths.sh"

# Runtime paths are shared with installer/catalog.sh so Dashboard discovery,
# CLI selection and installation always consume the same canonical catalog.
# shellcheck source=/dev/null
source "${CATALOG_PATHS}"

ACTION="${1:-list}"
shift || true

case "${ACTION}" in
    content)
        exec "${CATALOG}" content list "${1:-}" --json
        ;;
    content-definition)
        [[ -n "${1:-}" ]] || {
            printf '{"error":"missing_content_id"}\n'
            exit 2
        }
        exec "${CATALOG}" content show "${1}" --json
        ;;
    installed)
        [[ -n "${1:-}" ]] || {
            printf '{"error":"missing_instance_path"}\n'
            exit 2
        }
        exec "${CATALOG}" content list-installed "${1}" --json
        ;;
esac

json_error()
{
    local CODE="${1:-catalog_error}"
    local MESSAGE="${2:-Erro no catálogo.}"
    jq -nc --arg error "${CODE}" --arg message "${MESSAGE}" \
        '{error:$error,message:$message}'
}

runtime_file_by_id()
{
    local RUNTIME_ID="${1:-}"
    [[ -n "${RUNTIME_ID}" ]] || return 1
    catalog_runtime_find "${RUNTIME_ID}"
}

catalog_runtimes()
{
    catalog_runtime_list "${1:-}"
}

catalog_runtime()
{
    local RUNTIME_ID="${1:-}" FILE
    [[ -n "${RUNTIME_ID}" ]] || {
        json_error "missing_runtime_id" "Informe o ID do runtime."
        return 2
    }
    FILE="$(runtime_file_by_id "${RUNTIME_ID}")" || {
        json_error "runtime_not_found" "Runtime não encontrado: ${RUNTIME_ID}"
        return 2
    }
    jq '.' "${FILE}"
}

# -----------------------------------------------------------------------------
# Canonical resolver bridge
#
# Runtime discovery and resolution are owned by installer/version_resolvers.
# Dashboard must not maintain a second resolver whitelist. This bridge exports
# RuntimeDefinition configuration, invokes the canonical resolver in a subshell,
# and normalizes its result into the stable HTTP/UI contract.
# -----------------------------------------------------------------------------

resolver_name_for_file()
{
    jq -r '.version.resolver // empty' "$1"
}

resolver_file_for_name()
{
    local RESOLVER="${1:-}"
    [[ "${RESOLVER}" =~ ^[A-Za-z0-9_.-]+$ ]] || return 1
    local FILE="${RESOLVER_ROOT}/${RESOLVER}.sh"
    [[ -f "${FILE}" ]] || return 1
    printf '%s\n' "${FILE}"
}

canonical_resolver_call()
{
    local RUNTIME_FILE="${1:?runtime file required}"
    local RESOLVER="${2:?resolver required}"
    local RESOLVER_ACTION="${3:?resolver action required}"
    local SELECTOR="${4:-}"
    local RESOLVER_FILE

    RESOLVER_FILE="$(resolver_file_for_name "${RESOLVER}")" || return 2

    (
        export GAME_ID VARIANT_ID
        export VERSION_REPOSITORY VERSION_ASSET_PATTERN
        export VERSION_GAME_VERSION_ASSET_REGEX VERSION_DISCOVERY_LIMIT
        export PAPERMC_PROJECT PAPERMC_API_BASE FABRIC_META_BASE
        export BEDROCK_DOWNLOAD_PAGE BEDROCK_LINUX_BASE
        export PURPUR_PROJECT PURPUR_API_BASE QUILT_META_BASE YOUER_API_BASE
        export FORGE_MAVEN_BASE NEOFORGE_MAVEN_BASE SPONGE_MAVEN_BASE

        GAME_ID="$(jq -r '.game // empty' "${RUNTIME_FILE}")"
        VARIANT_ID="$(jq -r '.variant // empty' "${RUNTIME_FILE}")"
        VERSION_REPOSITORY="$(jq -r '.version.config.repository // empty' "${RUNTIME_FILE}")"
        VERSION_ASSET_PATTERN="$(jq -r '.version.config.asset_pattern // "*"' "${RUNTIME_FILE}")"
        VERSION_GAME_VERSION_ASSET_REGEX="$(jq -r '.version.config.game_version_asset_regex // empty' "${RUNTIME_FILE}")"
        VERSION_DISCOVERY_LIMIT="$(jq -r '.version.config.discovery_limit // 50' "${RUNTIME_FILE}")"
        PAPERMC_PROJECT="$(jq -r '.version.config.project // "paper"' "${RUNTIME_FILE}")"
        PAPERMC_API_BASE="$(jq -r '.version.config.api_base // "https://fill.papermc.io/v3"' "${RUNTIME_FILE}")"
        FABRIC_META_BASE="$(jq -r '.version.config.api_base // "https://meta.fabricmc.net/v2"' "${RUNTIME_FILE}")"
        BEDROCK_DOWNLOAD_PAGE="$(jq -r '.version.config.download_page // "https://www.minecraft.net/en-us/download/server/bedrock"' "${RUNTIME_FILE}")"
        BEDROCK_LINUX_BASE="$(jq -r '.version.config.linux_base // "https://www.minecraft.net/bedrockdedicatedserver/bin-linux"' "${RUNTIME_FILE}")"
        PURPUR_PROJECT="$(jq -r '.version.config.project // "purpur"' "${RUNTIME_FILE}")"
        PURPUR_API_BASE="$(jq -r '.version.config.api_base // "https://api.purpurmc.org/v2"' "${RUNTIME_FILE}")"
        QUILT_META_BASE="$(jq -r '.version.config.api_base // "https://meta.quiltmc.org/v3"' "${RUNTIME_FILE}")"
        YOUER_API_BASE="$(jq -r '.version.config.api_base // "https://api.mohistmc.com/project/youer"' "${RUNTIME_FILE}")"
        FORGE_MAVEN_BASE="$(jq -r '.version.config.maven_base // empty' "${RUNTIME_FILE}")"
        NEOFORGE_MAVEN_BASE="$(jq -r '.version.config.maven_base // empty' "${RUNTIME_FILE}")"
        SPONGE_MAVEN_BASE="$(jq -r '.version.config.maven_base // empty' "${RUNTIME_FILE}")"

        [[ -n "${FORGE_MAVEN_BASE}" ]] || unset FORGE_MAVEN_BASE
        [[ -n "${NEOFORGE_MAVEN_BASE}" ]] || unset NEOFORGE_MAVEN_BASE
        [[ -n "${SPONGE_MAVEN_BASE}" ]] || unset SPONGE_MAVEN_BASE

        # shellcheck source=/dev/null
        source "${RESOLVER_FILE}"
        declare -F version_resolver_execute >/dev/null 2>&1 || return 2
        version_resolver_execute \
            "${RESOLVER_ACTION}" \
            "${GAME_ID}" \
            "${VARIANT_ID}" \
            "${SELECTOR}"
    )
}

canonical_resolver_list()
{
    local RUNTIME_FILE="${1:?runtime file required}"
    local RESOLVER="${2:?resolver required}"
    local RESPONSE

    if ! resolver_file_for_name "${RESOLVER}" >/dev/null
    then
        json_error "unsupported_version_resolver" "Resolver de versão não suportado: ${RESOLVER}"
        return 2
    fi

    if ! RESPONSE="$(canonical_resolver_call "${RUNTIME_FILE}" "${RESOLVER}" list "" 2>/dev/null)"
    then
        json_error "resolver_request_failed" "Não foi possível consultar as versões deste runtime."
        return 1
    fi

    if ! jq -e 'type == "object" and (.versions | type) == "array"' >/dev/null 2>&1 <<<"${RESPONSE}"
    then
        json_error "resolver_invalid_response" "O resolver retornou uma resposta inválida."
        return 1
    fi

    printf '%s\n' "${RESPONSE}"
}

catalog_versions()
{
    local RUNTIME_ID="${1:-}" FILE STRATEGY RESOLVER RESPONSE STATUS

    [[ -n "${RUNTIME_ID}" ]] || {
        json_error "missing_runtime_id" "Informe o runtime."
        return 2
    }
    FILE="$(runtime_file_by_id "${RUNTIME_ID}")" || {
        json_error "runtime_not_found" "Runtime não encontrado: ${RUNTIME_ID}"
        return 2
    }

    STRATEGY="$(jq -r '.version.strategy // "static"' "${FILE}")"
    if [[ "${STRATEGY}" == "static" ]]
    then
        jq -c '[{value:(.version.value // .version.version // "current" | tostring),label:(.version.value // .version.version // "Versão atual / recomendada" | tostring),recommended:true,raw:.version}]' "${FILE}"
        return
    fi

    RESOLVER="$(resolver_name_for_file "${FILE}")"
    [[ -n "${RESOLVER}" ]] || {
        json_error "missing_version_resolver" "Runtime dinâmico sem resolver de versão."
        return 2
    }

    if RESPONSE="$(canonical_resolver_list "${FILE}" "${RESOLVER}")"
    then
        :
    else
        STATUS=$?
        printf '%s\n' "${RESPONSE}"
        return "${STATUS}"
    fi

    jq -c '
        [.versions[]? |
            (.version // .minecraft_versions[0] // empty) |
            select(. != null and tostring != "") |
            tostring] |
        reduce .[] as $value ([]; if index($value) then . else . + [$value] end) |
        map({value:.,label:.,recommended:false}) |
        if length > 0 then .[0].recommended = true else . end
    ' <<<"${RESPONSE}"
}

catalog_builds()
{
    local RUNTIME_ID="${1:-}" VERSION="${2:-}" FILE STRATEGY RESOLVER RESPONSE BUILDS RESOLVED STATUS

    [[ -n "${RUNTIME_ID}" ]] || {
        json_error "missing_runtime_id" "Informe o runtime."
        return 2
    }
    [[ -n "${VERSION}" ]] || {
        json_error "missing_version" "Informe a versão do runtime."
        return 2
    }
    FILE="$(runtime_file_by_id "${RUNTIME_ID}")" || {
        json_error "runtime_not_found" "Runtime não encontrado: ${RUNTIME_ID}"
        return 2
    }

    STRATEGY="$(jq -r '.version.strategy // "static"' "${FILE}")"
    if [[ "${STRATEGY}" == "static" ]]
    then
        jq -c '[{value:(.version.build // "current" | tostring),label:(if .version.build then "Build recomendada" else "Build atual / recomendada" end),recommended:true}]' "${FILE}"
        return
    fi

    RESOLVER="$(resolver_name_for_file "${FILE}")"
    [[ -n "${RESOLVER}" ]] || {
        json_error "missing_version_resolver" "Runtime dinâmico sem resolver de versão."
        return 2
    }

    if RESPONSE="$(canonical_resolver_list "${FILE}" "${RESOLVER}")"
    then
        :
    else
        STATUS=$?
        printf '%s\n' "${RESPONSE}"
        return "${STATUS}"
    fi

    BUILDS="$(jq -c --arg version "${VERSION}" '
        [.versions[]? |
            select((.version // "" | tostring) == $version) |
            (.build // .full // empty) |
            select(. != null and tostring != "") |
            tostring] |
        reduce .[] as $value ([]; if index($value) then . else . + [$value] end) |
        map({value:.,label:("Build " + .),recommended:false})
    ' <<<"${RESPONSE}")"

    if [[ "$(jq 'length' <<<"${BUILDS}")" -gt 0 ]]
    then
        if RESOLVED="$(canonical_resolver_call "${FILE}" "${RESOLVER}" resolve "${VERSION}" 2>/dev/null)" && \
           ! jq -e '.error?' >/dev/null 2>&1 <<<"${RESOLVED}"
        then
            local RECOMMENDED_BUILD
            RECOMMENDED_BUILD="$(jq -r '.build // .tag // empty | tostring' <<<"${RESOLVED}")"
            if [[ -n "${RECOMMENDED_BUILD}" ]]
            then
                BUILDS="$(jq -c --arg recommended "${RECOMMENDED_BUILD}" '
                    map(.value as $value |
                        .recommended =
                            ($value == $recommended or
                             ($recommended | endswith("-" + $value))))
                ' <<<"${BUILDS}")"
            fi
        fi
        printf '%s\n' "${BUILDS}"
        return
    fi

    if ! RESOLVED="$(canonical_resolver_call "${FILE}" "${RESOLVER}" resolve "${VERSION}" 2>/dev/null)"
    then
        json_error "resolver_request_failed" "Não foi possível consultar as builds desta versão."
        return 1
    fi

    if jq -e '.error?' >/dev/null 2>&1 <<<"${RESOLVED}"
    then
        json_error "build_not_found" "Nenhuma build compatível foi encontrada para esta versão."
        return 1
    fi

    jq -c '[{value:(.build // .tag // "current" | tostring),label:("Build " + (.build // .tag // "current" | tostring)),recommended:true,raw:.}]' <<<"${RESOLVED}"
}

catalog_search()
{
    local PROVIDER="${1:-modrinth}" QUERY="${2:-}" GAME="${3:-minecraft}"
    local GAME_VERSION="${4:-}" LOADER="${5:-}" CONTENT_TYPE="${6:-mod}" LIMIT="${7:-20}"

    [[ "${PROVIDER}" == "modrinth" ]] || {
        json_error "unsupported_search_provider" "Provider de busca não suportado: ${PROVIDER}"
        return 2
    }
    [[ -n "${QUERY}" ]] || {
        json_error "missing_query" "Informe um termo de busca."
        return 2
    }
    [[ "${GAME}" == "minecraft" ]] || {
        json_error "unsupported_game" "A busca Modrinth está disponível inicialmente para Minecraft."
        return 2
    }
    [[ -f "${PROVIDER_LOADER}" ]] || {
        json_error "provider_loader_missing" "Provider Loader não encontrado."
        return 1
    }

    # shellcheck source=/dev/null
    source "${PROVIDER_LOADER}"
    provider_require "${PROVIDER}" || {
        json_error "provider_unavailable" "Provider ${PROVIDER} não disponível."
        return 1
    }
    declare -F provider_search >/dev/null 2>&1 || {
        json_error "provider_search_unsupported" "Provider não implementa busca."
        return 1
    }
    provider_search "${QUERY}" "${GAME_VERSION}" "${LOADER}" "${CONTENT_TYPE}" "${LIMIT}"
}

case "${ACTION}" in
    compatibility)
        [[ -n "${1:-}" ]] || {
            printf '{"error":"missing_compatibility_request"}\n'
            exit 2
        }
        exec "${CATALOG}" compatibility check "$1" --json
        ;;
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
    list|editions|variants|versions-legacy|resolve|prepare)
        LEGACY_ACTION="${ACTION}"
        [[ "${ACTION}" != "versions-legacy" ]] || LEGACY_ACTION="versions"
        exec "${CATALOG}" "${LEGACY_ACTION}" "$@"
        ;;
    search)
        catalog_search "$@"
        ;;
    *)
        jq -nc --arg action "${ACTION}" '{error:"invalid_catalog_action",action:$action,actions:["runtimes","runtime","versions","builds","search","list","editions","variants","resolve","prepare"]}'
        exit 2
        ;;
esac
