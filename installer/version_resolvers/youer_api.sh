#!/usr/bin/env bash
# Capivara DSM - Youer resolver using MohistMC's official APIs.
set -Eeuo pipefail

YOUER_API_BASE="${YOUER_API_BASE:-https://mohistmc.com/api/v2/projects/youer}"
YOUER_LEGACY_API_BASE="${YOUER_LEGACY_API_BASE:-https://api.mohistmc.com/project/youer}"
YOUER_GITHUB_BRANCHES_API="${YOUER_GITHUB_BRANCHES_API:-https://api.github.com/repos/MohistMC/Youer/branches?per_page=100}"
YOUER_DISCOVERY_LIMIT="${YOUER_DISCOVERY_LIMIT:-25}"

youer_error(){ echo "[DSM][DISCOVERY][YOUER][ERROR] $*" >&2; }
youer_get(){ curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 "$1"; }

youer_project()
{
    youer_get "${YOUER_API_BASE}"
}

youer_discovery_project()
{
    local PROJECT BRANCHES VERSIONS
    if PROJECT="$(youer_project 2>/dev/null)" && \
       jq -e 'type=="object" and (.versions|type)=="array" and (.versions|length)>0' >/dev/null 2>&1 <<<"${PROJECT}"
    then
        printf '%s\n' "${PROJECT}"
        return 0
    fi

    if ! BRANCHES="$(youer_get "${YOUER_GITHUB_BRANCHES_API}" 2>/dev/null)" || \
       ! jq -e 'type=="array"' >/dev/null 2>&1 <<<"${BRANCHES}"
    then
        youer_error "official API returned no versions and GitHub branch fallback failed"
        return 1
    fi

    VERSIONS="$(
        jq -r '
          .[]?.name
          | tostring
          | select(test("^[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))
        ' <<<"${BRANCHES}" | sort -V | jq -Rsc 'split("\n") | map(select(length > 0))'
    )"
    if ! jq -e 'length > 0' >/dev/null 2>&1 <<<"${VERSIONS}"
    then
        youer_error "no release branches were published by the official Youer repository"
        return 1
    fi
    jq -nc --argjson versions "${VERSIONS}" '{versions:$versions,source:"github-branches"}'
}

youer_builds()
{
    local VERSION="$1" RESPONSE
    if RESPONSE="$(youer_get "${YOUER_API_BASE}/${VERSION}/builds" 2>/dev/null)" &&        jq -e 'type=="object" and (.builds|type)=="array"' >/dev/null 2>&1 <<<"${RESPONSE}"
    then
        printf '%s\n' "${RESPONSE}"
        return 0
    fi

    if RESPONSE="$(youer_get "${YOUER_LEGACY_API_BASE}/${VERSION}/builds" 2>/dev/null)" &&        jq -e 'type=="array"' >/dev/null 2>&1 <<<"${RESPONSE}"
    then
        jq -nc --argjson builds "${RESPONSE}" '{builds:$builds,source:"legacy"}'
        return 0
    fi

    youer_error "unable to query builds for ${VERSION}"
    return 1
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
    local PROJECT LIMIT VERSION BUILDS VERSION_ENTRY
    local OUTPUT='[]'
    PROJECT="$(youer_discovery_project)" || return 1
    LIMIT="${YOUER_DISCOVERY_LIMIT}"
    [[ "${LIMIT}" =~ ^[0-9]+$ ]] || LIMIT=25
    (( LIMIT > 0 )) || LIMIT=25

    while IFS= read -r VERSION
    do
        [[ -n "${VERSION}" ]] || continue

        # Keep version discovery independent from build discovery. A temporary
        # build endpoint failure must not collapse the Customer selector to the
        # generic "current" fallback.
        VERSION_ENTRY="$(jq -nc --arg version "${VERSION}" '{
          version:$version,
          minecraft_versions:[$version],
          stable:true
        }')"
        OUTPUT="$(jq -nc --argjson current "${OUTPUT}" --argjson entry "${VERSION_ENTRY}" '$current + [$entry]')"

        if BUILDS="$(youer_builds "${VERSION}")"; then
            OUTPUT="$(jq -c               --arg version "${VERSION}"               --argjson current "${OUTPUT}" '
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
        fi
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

    PROJECT="$(youer_discovery_project)" || return 1
    if [[ "${VERSION}" == "current" || "${VERSION}" == "latest" ]]; then
        VERSION="$(jq -r '(.versions // []) | map(tostring) | last // empty' <<<"${PROJECT}")"
    fi
    [[ -n "${VERSION}" ]] || { youer_error "official API returned no versions"; return 1; }

    if ! youer_version_exists "${PROJECT}" "${VERSION}"; then
        jq -nc           --arg selector "${SELECTOR}"           --argjson supported "$(jq -c '(.versions // []) | map(tostring)' <<<"${PROJECT}")"           '{error:"youer_version_not_supported",selector:$selector,supported_versions:$supported}'
        return 1
    fi

    if ! BUILDS="$(youer_builds "${VERSION}")"; then
        # MohistMC documents a canonical latest-build download route. When build
        # listing is temporarily unavailable, keep provisioning usable for an
        # unpinned request instead of failing the Customer workflow outright.
        if [[ -z "${BUILD:-}" ]]; then
            BUILD="latest"
            URL="${YOUER_API_BASE}/${VERSION}/builds/latest/download"
            jq -nc --arg version "${VERSION}" --arg build "${BUILD}" --arg url "${URL}" '
              {
                version:$version,
                build:$build,
                minecraft_versions:[$version],
                provider:"http",
                selected_asset:{name:"server.jar",url:$url,content_type:"application/java-archive"},
                install:{url:$url,asset:"server.jar"}
              }'
            return 0
        fi
        return 1
    fi
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
    [[ -n "${URL}" ]] || URL="${YOUER_LEGACY_API_BASE}/${VERSION}/builds/${BUILD}/download"

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
