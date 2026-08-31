#!/usr/bin/env bash
# Capivara DSM - canonical Execution Environment and Content Catalog
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_ROOT="${DSM_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CATALOG_ROOT="${DSM_CATALOG_ROOT:-${DSM_ROOT}/catalog/v2}"
ENVIRONMENT_ROOT="${CATALOG_ROOT}/runtimes"
CONTENT_ROOT="${CATALOG_ROOT}/content"
RESOLVER_ROOT="${DSM_ROOT}/installer/version_resolvers"
COMPATIBILITY_RESOLVER="${DSM_ROOT}/installer/compatibility_resolver.sh"
CONTENT_PLANNER="${DSM_ROOT}/installer/content_planner.sh"
CONTENT_MANAGER="${DSM_ROOT}/installer/content_manager.sh"
FORMATTER="${DSM_ROOT}/installer/catalog_formatter.sh"
CATALOG_PATH_RESOLVER="${DSM_ROOT}/installer/catalog_paths.sh"
OUTPUT_FORMAT="human"

if [[ ! -f "${CATALOG_PATH_RESOLVER}" ]]
then
    echo "[DSM][CATALOG][ERROR] Catalog path resolver not found: ${CATALOG_PATH_RESOLVER}" >&2
    exit 1
fi

# shellcheck source=/dev/null
source "${CATALOG_PATH_RESOLVER}"

CATALOG_ARGS=()
for CATALOG_ARG in "$@"; do
    case "${CATALOG_ARG}" in
        --json) OUTPUT_FORMAT="json" ;;
        *) CATALOG_ARGS+=("${CATALOG_ARG}") ;;
    esac
done
set -- "${CATALOG_ARGS[@]}"

catalog_error(){ echo "[DSM][CATALOG][ERROR] $*" >&2; }

catalog_output()
{
    local STYLE="$1"
    if [[ "${OUTPUT_FORMAT}" == "json" ]]; then jq .; else "${FORMATTER}" "${STYLE}"; fi
}

catalog_find()
{
    local ROOT="$1" ID="$2" FILE
    while IFS= read -r -d '' FILE; do
        if jq -e --arg id "${ID}" '.id == $id' "${FILE}" >/dev/null; then
            printf '%s\n' "${FILE}"
            return 0
        fi
    done < <(find "${ROOT}" -type f -name '*.json' -print0 2>/dev/null)
    return 1
}

catalog_list()
{
    local ROOT="$1" GAME="${2:-}"
    find "${ROOT}" -type f -name '*.json' -print0 2>/dev/null |
        xargs -0 -r jq -c 'select(.schema_version == 2)' |
        jq -sc --arg game "${GAME}" '
          map(select($game == "" or .game == $game)) |
          sort_by(.game, .edition // "", .content_type // "", .variant // "", .id)'
}

catalog_show()
{
    local ROOT="$1" ID="$2" FILE
    FILE="$(catalog_find "${ROOT}" "${ID}")" || {
        catalog_error "Definition not found: ${ID}"
        return 1
    }
    jq . "${FILE}"
}

catalog_runtime_show()
{
    local ID="$1" FILE
    FILE="$(catalog_runtime_find "${ID}")" || {
        catalog_error "Definition not found: ${ID}"
        return 1
    }
    jq . "${FILE}"
}

catalog_configure_resolver()
{
    local FILE="$1"
    GAME_ID="$(jq -r '.game' "${FILE}")"
    VARIANT_ID="$(jq -r '.variant' "${FILE}")"
    VERSION_REPOSITORY="$(jq -r '.version.config.repository // empty' "${FILE}")"
    VERSION_ASSET_PATTERN="$(jq -r '.version.config.asset_pattern // "*"' "${FILE}")"
    VERSION_GAME_VERSION_ASSET_REGEX="$(jq -r '.version.config.game_version_asset_regex // empty' "${FILE}")"
    VERSION_DISCOVERY_LIMIT="$(jq -r '.version.config.discovery_limit // 50' "${FILE}")"
    PAPERMC_PROJECT="$(jq -r '.version.config.project // "paper"' "${FILE}")"
    PAPERMC_API_BASE="$(jq -r '.version.config.api_base // "https://fill.papermc.io/v3"' "${FILE}")"
    FABRIC_META_BASE="$(jq -r '.version.config.api_base // "https://meta.fabricmc.net/v2"' "${FILE}")"
    BEDROCK_DOWNLOAD_PAGE="$(jq -r '.version.config.download_page // "https://www.minecraft.net/en-us/download/server/bedrock"' "${FILE}")"
    BEDROCK_LINUX_BASE="$(jq -r '.version.config.linux_base // "https://www.minecraft.net/bedrockdedicatedserver/bin-linux"' "${FILE}")"
    export GAME_ID VARIANT_ID VERSION_REPOSITORY VERSION_ASSET_PATTERN
    export VERSION_GAME_VERSION_ASSET_REGEX VERSION_DISCOVERY_LIMIT
    export PAPERMC_PROJECT PAPERMC_API_BASE FABRIC_META_BASE
    export BEDROCK_DOWNLOAD_PAGE BEDROCK_LINUX_BASE
}

catalog_resolve_static()
{
    local FILE="$1" SELECTOR="$2"
    jq -c --arg selector "${SELECTOR}" '
      (.version.value // (if $selector=="latest" or $selector=="current" then "current" else $selector end)) as $version |
      (.version.build // $version) as $build |
      {
        version:$version,
        build:$build,
        provider:.artifact.provider,
        repository:(.artifact.repository // null),
        tag:(.artifact.tag // $build),
        selected_asset:(if .artifact.url then {
          name:(.artifact.asset // .process.executable),
          url:.artifact.url,
          sha256:(.artifact.sha256 // null)
        } elif .artifact.asset then {name:.artifact.asset} else null end),
        install:{
          package_id:(.artifact.package_id // null),
          repository:(.artifact.repository // null),
          tag:(.artifact.tag // $build),
          asset:(.artifact.asset // null),
          url:(.artifact.url // null),
          sha256:(.artifact.sha256 // null),
          archive_type:(.artifact.archive_type // null)
        }
      }' "${FILE}"
}

catalog_resolve_dynamic()
{
    local FILE="$1" SELECTOR="$2" RESOLVER RESOLVER_FILE
    RESOLVER="$(jq -r '.version.resolver // empty' "${FILE}")"
    [[ "${RESOLVER}" =~ ^[A-Za-z0-9_.-]+$ ]] || {
        catalog_error "Invalid resolver: ${RESOLVER}"
        return 1
    }
    RESOLVER_FILE="${RESOLVER_ROOT}/${RESOLVER}.sh"
    [[ -f "${RESOLVER_FILE}" ]] || {
        catalog_error "Resolver not found: ${RESOLVER}"
        return 1
    }
    catalog_configure_resolver "${FILE}"
    # shellcheck source=/dev/null
    source "${RESOLVER_FILE}"
    version_resolver_execute resolve "${GAME_ID}" "${VARIANT_ID}" "${SELECTOR}"
}

catalog_resolve_environment()
{
    local FILE="$1" SELECTOR="$2" STRATEGY
    STRATEGY="$(jq -r '.version.strategy' "${FILE}")"
    case "${STRATEGY}" in
        static) catalog_resolve_static "${FILE}" "${SELECTOR}" ;;
        dynamic) catalog_resolve_dynamic "${FILE}" "${SELECTOR}" ;;
        *) catalog_error "Unsupported version strategy: ${STRATEGY}"; return 1 ;;
    esac
}

catalog_prepare_environment()
{
    local ID="$1" SELECTOR="$2" FILE RESOLVED
    FILE="$(catalog_runtime_find "${ID}")" || {
        catalog_error "Execution environment not found: ${ID}"
        return 1
    }
    RESOLVED="$(catalog_resolve_environment "${FILE}" "${SELECTOR}")" || return 1
    if jq -e '.error?' >/dev/null <<<"${RESOLVED}"; then
        echo "${RESOLVED}"
        return 1
    fi

    jq -c --argjson definition "$(jq -c . "${FILE}")" --argjson resolved "${RESOLVED}" '
  ($resolved.selected_asset // null) as $asset |
  ($resolved.install // {}) as $resolved_install |
  ($resolved.request // {}) as $request |
  {
    schema_version:2,
    kind:"RuntimeSelection",
    runtime_definition:$definition.id,
    game:$definition.game,
    edition:$definition.edition,
    variant:$definition.variant,
    version:($resolved.version // $definition.version.value // "current"),
    build:($resolved.build // $resolved.tag // $definition.version.build // "current"),
    process_engine:$definition.process.engine,
    artifact_mode:($definition.process.artifact_mode // "executable"),
    provider:($resolved.provider // $definition.artifact.provider),
    auth:($definition.artifact.auth // "anonymous"),
    source_repository:($resolved.repository // $definition.artifact.repository // null),
    tag:($resolved.tag // $definition.artifact.tag // $resolved.build // null),
    request:$request,
    asset:($asset // (if $definition.artifact.asset then {
      name:$definition.artifact.asset,
      url:($definition.artifact.url // null),
      sha256:($definition.artifact.sha256 // null)
    } else null end)),
        archive:{type:($resolved_install.archive_type // $definition.artifact.archive_type // null)},
        install:($resolved_install + {
          package_id:($resolved_install.package_id // $definition.artifact.package_id // null),
          repository:($resolved_install.repository // $definition.artifact.repository // null),
          url:($resolved_install.url // $definition.artifact.url // null),
          asset:($resolved_install.asset // $definition.artifact.asset // ($asset.name // null)),
          sha256:($resolved_install.sha256 // $definition.artifact.sha256 // ($asset.sha256 // null)),
          archive_type:($resolved_install.archive_type // $definition.artifact.archive_type // null)
        }),
        install_dir:($definition.installation.directory // ("/opt/dsm/game-data/"+$definition.game+"/"+$definition.variant)),
        installer:($definition.installation.installer // null),
        executable:$definition.process.executable,
        build_config:($definition.build // {}),
        resolved_at:(now|floor)
      }' <<<"{}"
}

catalog_usage()
{
    cat <<'EOF'
Usage:
  catalog.sh runtime list [GAME]
  catalog.sh runtime show RUNTIME_ID
  catalog.sh runtime prepare RUNTIME_ID SELECTOR
  catalog.sh content list [GAME]
  catalog.sh content show CONTENT_ID
  catalog.sh content plan REQUEST.json INSTANCE_PATH
  catalog.sh content install REQUEST.json INSTANCE_PATH
  catalog.sh content remove INSTANCE_PATH CONTENT_ID
  catalog.sh content list-installed INSTANCE_PATH
  catalog.sh content verify INSTANCE_PATH
  catalog.sh content rollback INSTANCE_PATH
  catalog.sh compatibility check REQUEST.json
  catalog.sh providers

Add --json to any command for machine-readable output.
EOF
}

case "${1:-}" in
    runtime)
        case "${2:-}" in
            list) catalog_runtime_list "${3:-}" | catalog_output runtime-list ;;
            show) [[ $# -eq 3 ]] || { catalog_usage; exit 2; }; catalog_runtime_show "$3" | catalog_output definition ;;
            prepare) [[ $# -eq 4 ]] || { catalog_usage; exit 2; }; catalog_prepare_environment "$3" "$4" | catalog_output selection ;;
            *) catalog_usage; exit 2 ;;
        esac
        ;;
    content)
        case "${2:-}" in
            list) catalog_list "${CONTENT_ROOT}" "${3:-}" | catalog_output content-list ;;
            show) [[ $# -eq 3 ]] || { catalog_usage; exit 2; }; catalog_show "${CONTENT_ROOT}" "$3" | catalog_output definition ;;
            plan) [[ $# -eq 4 ]] || { catalog_usage; exit 2; }; "${CONTENT_PLANNER}" plan "$3" "$4" | catalog_output plan ;;
            install) [[ $# -eq 4 ]] || { catalog_usage; exit 2; }; DSM_OUTPUT_FORMAT="${OUTPUT_FORMAT}" "${CONTENT_MANAGER}" install "$3" "$4" ;;
            remove) [[ $# -eq 4 ]] || { catalog_usage; exit 2; }; DSM_OUTPUT_FORMAT="${OUTPUT_FORMAT}" "${CONTENT_MANAGER}" remove "$3" "$4" ;;
            list-installed) [[ $# -eq 3 ]] || { catalog_usage; exit 2; }; DSM_OUTPUT_FORMAT="${OUTPUT_FORMAT}" "${CONTENT_MANAGER}" list-installed "$3" ;;
            verify) [[ $# -eq 3 ]] || { catalog_usage; exit 2; }; DSM_OUTPUT_FORMAT="${OUTPUT_FORMAT}" "${CONTENT_MANAGER}" verify "$3" ;;
            rollback) [[ $# -eq 3 ]] || { catalog_usage; exit 2; }; DSM_OUTPUT_FORMAT="${OUTPUT_FORMAT}" "${CONTENT_MANAGER}" rollback "$3" ;;
            *) catalog_usage; exit 2 ;;
        esac
        ;;
    compatibility)
        [[ "${2:-}" == "check" && $# -eq 3 ]] || { catalog_usage; exit 2; }
        "${COMPATIBILITY_RESOLVER}" check "$3" | catalog_output compatibility
        ;;
    providers) jq . "${CATALOG_ROOT}/providers/catalog-providers.json" | catalog_output providers ;;
    *) catalog_usage; exit 2 ;;
esac
