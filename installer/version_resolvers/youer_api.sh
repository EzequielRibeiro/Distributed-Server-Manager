#!/usr/bin/env bash
# Capivara DSM - Youer resolver using the official MohistMC JSON API v2.
set -Eeuo pipefail

YOUER_API_BASE="${YOUER_API_BASE:-https://mohistmc.com/api/v2/projects/youer}"
YOUER_DISCOVERY_LIMIT="${YOUER_DISCOVERY_LIMIT:-25}"

youer_error(){ echo "[DSM][DISCOVERY][YOUER][ERROR] $*" >&2; }
youer_get(){ curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 "$1"; }

youer_project()
{
    youer_get "${YOUER_API_BASE}"
}

youer_builds()
{
    local VERSION="$1"
    youer_get "${YOUER_API_BASE}/${VERSION}/builds"
}

youer_version_exists()
{
    local PROJECT="$1" VERSION="$2"
    jq -e --arg version "${VERSION}" '
      (.versions // [])
      | map(tostring)
      | index($version) != null
    ' <<<"${PROJECT}" >/dev/null
}

youer_build_number()
{
    jq -r '.number // .id // .build // empty | tostring'
}

youer_list()
{
    local PROJECT LIMIT VERSION BUILDS
    local OUTPUT='[]'
    PROJECT="$(youer_project)" || return 1
    LIMIT="${YOUER_DISCOVERY_LIMIT}"
    [[ "${LIMIT}" =~ ^[0-9]+$ ]] || LIMIT=25
    (( LIMIT > 0 )) || LIMIT=25

    while IFS= read -r VERSION
    do
        [[ -n "${VERSION}" ]] || continue
        BUILDS="$(youer_builds "${VERSION}")" || continue
        OUTPUT="$(jq -c           --arg version "${VERSION}"           --argjson current "${OUTPUT}" '
          ($current + [
            (.builds // [])[]
            | (.number // .id // .build // empty | tostring) as $build
            | select($build != "")
            | {
                version:$version,
                build:$build,
                minecraft_versions:[$version],
                stable:true
              }
          ])
        ' <<<"${BUILDS}")"
    done < <(
        jq -r --argjson limit "${LIMIT}" '
          (.versions // [])
          | map(tostring)
          | reverse
          | .[0:$limit][]
        ' <<<"${PROJECT}"
    )

    jq -nc --argjson versions "${OUTPUT}" '
      {
        game:"minecraft",
        variant:"youer",
        source:"mohistmc-api-v2",
        versions:$versions
      }'
}

youer_resolve()
{
    local SELECTOR="${1:-}" VERSION BUILD PROJECT BUILDS BUILD_ITEM URL
    [[ -n "${SELECTOR}" ]] || { youer_error "selector is required"; return 2; }
    IFS='@' read -r VERSION BUILD <<<"${SELECTOR}"

    PROJECT="$(youer_project)" || return 1
    if [[ "${VERSION}" == "current" || "${VERSION}" == "latest" ]]; then
        VERSION="$(jq -r '(.versions // []) | map(tostring) | last // empty' <<<"${PROJECT}")"
    fi
    [[ -n "${VERSION}" ]] || { youer_error "official API returned no versions"; return 1; }

    if ! youer_version_exists "${PROJECT}" "${VERSION}"; then
        jq -nc           --arg selector "${SELECTOR}"           --argjson supported "$(jq -c '(.versions // []) | map(tostring)' <<<"${PROJECT}")"           '{error:"youer_version_not_supported",selector:$selector,supported_versions:$supported}'
        return 1
    fi

    BUILDS="$(youer_builds "${VERSION}")" || return 1
    if [[ -n "${BUILD:-}" ]]; then
        BUILD_ITEM="$(jq -c --arg build "${BUILD}" '
          [(.builds // [])[] | select(((.number // .id // .build // empty)|tostring)==$build)] | first // empty
        ' <<<"${BUILDS}")"
        [[ -n "${BUILD_ITEM}" ]] || {
            jq -nc --arg version "${VERSION}" --arg build "${BUILD}"               '{error:"youer_build_not_found",version:$version,build:$build}'
            return 1
        }
    else
        BUILD_ITEM="$(jq -c '(.builds // []) | last // empty' <<<"${BUILDS}")"
        [[ -n "${BUILD_ITEM}" ]] || { youer_error "official API returned no builds for ${VERSION}"; return 1; }
        BUILD="$(youer_build_number <<<"${BUILD_ITEM}")"
    fi

    [[ -n "${BUILD}" ]] || BUILD="$(youer_build_number <<<"${BUILD_ITEM}")"
    URL="$(jq -r '.url // .download_url // empty' <<<"${BUILD_ITEM}")"
    [[ -n "${URL}" ]] || URL="${YOUER_API_BASE}/${VERSION}/builds/${BUILD}/download"

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
