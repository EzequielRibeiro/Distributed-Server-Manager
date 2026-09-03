#!/usr/bin/env bash
set -Eeuo pipefail

PURPUR_API_BASE="${PURPUR_API_BASE:-https://api.purpurmc.org/v2}"
PURPUR_PROJECT="${PURPUR_PROJECT:-purpur}"
PURPUR_USER_AGENT="${PURPUR_USER_AGENT:-Capivara-DSM/1.0 (https://github.com/EzequielRibeiro/Distributed-Server-Manager)}"

purpur_error(){ echo "[DSM][DISCOVERY][PURPUR][ERRO] $*" >&2; }

purpur_get()
{
    local URL="${1:-}"
    [[ -n "${URL}" ]] || return 2
    curl --fail --silent --show-error --location \
        --connect-timeout 15 --max-time 45 \
        --header "User-Agent: ${PURPUR_USER_AGENT}" \
        --header "Accept: application/json" \
        "${URL}"
}

purpur_list()
{
    local RAW
    RAW="$(purpur_get "${PURPUR_API_BASE}/${PURPUR_PROJECT}")" || return 1
    jq -c \
      --arg game "${GAME_ID:-minecraft}" \
      --arg variant "${VARIANT_ID:-purpur}" \
      --arg project "${PURPUR_PROJECT}" '
      {
        game:$game,
        variant:$variant,
        source:"purpur-v2",
        project:$project,
        versions:(.versions | reverse | map({version:.,minecraft_versions:[.],provider:"http"}))
      }' <<<"${RAW}"
}

purpur_parse_selector()
{
    local SELECTOR="${1:-}"
    local VERSION BUILD
    VERSION="${SELECTOR%%@*}"
    BUILD=""
    if [[ "${SELECTOR}" == *"@"* ]]; then BUILD="${SELECTOR#*@}"; fi
    [[ -n "${VERSION}" ]] || return 1
    printf '%s\t%s\n' "${VERSION}" "${BUILD}"
}

purpur_resolve()
{
    local SELECTOR="${1:-}"
    local VERSION BUILD RAW SELECTED DOWNLOAD_URL
    IFS=$'\t' read -r VERSION BUILD < <(purpur_parse_selector "${SELECTOR}") || {
        purpur_error "Seletor inválido: ${SELECTOR}"
        return 1
    }

    RAW="$(purpur_get "${PURPUR_API_BASE}/${PURPUR_PROJECT}/${VERSION}")" || return 1
    if [[ -n "${BUILD}" ]]; then
        jq -e --arg build "${BUILD}" '(.builds.all // []) | map(tostring) | index($build) != null' <<<"${RAW}" >/dev/null \
            || { jq -nc --arg version "${VERSION}" --arg build "${BUILD}" '{error:"build_not_found",version:$version,build:$build}'; return 1; }
        SELECTED="${BUILD}"
    else
        SELECTED="$(jq -r '.builds.latest // empty' <<<"${RAW}")"
        [[ -n "${SELECTED}" ]] || { jq -nc --arg version "${VERSION}" '{error:"build_not_found",version:$version,build:"latest"}'; return 1; }
    fi

    DOWNLOAD_URL="${PURPUR_API_BASE}/${PURPUR_PROJECT}/${VERSION}/${SELECTED}/download"
    jq -nc \
      --arg game "${GAME_ID:-minecraft}" \
      --arg variant "${VARIANT_ID:-purpur}" \
      --arg version "${VERSION}" \
      --arg build "${SELECTED}" \
      --arg url "${DOWNLOAD_URL}" '
      {
        game:$game,
        variant:$variant,
        source:"purpur-v2",
        version:$version,
        minecraft_versions:[$version],
        build:$build,
        provider:"http",
        selected_asset:{name:"server.jar",url:$url,content_type:"application/java-archive"},
        install:{url:$url,asset:"server.jar"}
      }'
}

version_resolver_execute()
{
    local ACTION="${1:-}"
    local SELECTOR="${4:-}"
    case "${ACTION}" in
        list) purpur_list ;;
        resolve) purpur_resolve "${SELECTOR}" ;;
        *) purpur_error "Ação desconhecida: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
