#!/usr/bin/env bash
# Capivara DSM - Youer resolver using the official MohistMC JSON API.
set -Eeuo pipefail

YOUER_API_BASE="${YOUER_API_BASE:-https://api.mohistmc.com/project/youer}"
YOUER_SUPPORTED_VERSION="1.21.1"

youer_error(){ echo "[DSM][DISCOVERY][YOUER][ERROR] $*" >&2; }
youer_get(){ curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 "$1"; }

youer_builds()
{
    local VERSION="$1"
    [[ "${VERSION}" == "${YOUER_SUPPORTED_VERSION}" ]] || {
        youer_error "unsupported Minecraft version: ${VERSION}"
        return 2
    }
    youer_get "${YOUER_API_BASE}/${VERSION}/builds"
}

youer_list()
{
    youer_builds "${YOUER_SUPPORTED_VERSION}" | jq -c --arg version "${YOUER_SUPPORTED_VERSION}" '
      {
        game:"minecraft",
        variant:"youer",
        source:"mohistmc-api",
        versions:[.[] | {
          version:$version,
          build:(.id|tostring),
          minecraft_versions:[$version],
          stable:true
        }]
      }'
}

youer_resolve()
{
    local SELECTOR="${1:-}" VERSION BUILD BUILDS URL
    [[ -n "${SELECTOR}" ]] || { youer_error "selector is required"; return 2; }
    IFS='@' read -r VERSION BUILD <<<"${SELECTOR}"
    [[ "${VERSION}" == "${YOUER_SUPPORTED_VERSION}" ]] || {
        jq -nc --arg selector "${SELECTOR}" --arg supported "${YOUER_SUPPORTED_VERSION}" \
          '{error:"youer_version_not_supported",selector:$selector,supported_versions:[$supported]}'
        return 1
    }

    BUILDS="$(youer_builds "${VERSION}")" || return 1
    if [[ -n "${BUILD:-}" ]]; then
        jq -e --arg build "${BUILD}" 'map(select((.id|tostring)==$build)) | length == 1' <<<"${BUILDS}" >/dev/null || {
            jq -nc --arg version "${VERSION}" --arg build "${BUILD}" \
              '{error:"youer_build_not_found",version:$version,build:$build}'
            return 1
        }
    else
        BUILD="$(jq -r '.[0].id // empty' <<<"${BUILDS}")"
        [[ -n "${BUILD}" ]] || { youer_error "official API returned no builds for ${VERSION}"; return 1; }
    fi

    URL="${YOUER_API_BASE}/${VERSION}/builds/${BUILD}/download"
    jq -nc --arg version "${VERSION}" --arg build "${BUILD}" --arg url "${URL}" '
      {
        version:$version,
        build:$build,
        minecraft_versions:[$version],
        provider:"http",
        selected_asset:{name:"server.jar",url:$url,content_type:"application/java-archive"},
        install:{url:$url,asset:"server.jar"}
      }'
}

version_resolver_execute()
{
    local ACTION="${1:-}" SELECTOR="${4:-}"
    case "${ACTION}" in
        list) youer_list ;;
        resolve) youer_resolve "${SELECTOR}" ;;
        *) youer_error "unknown action: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
