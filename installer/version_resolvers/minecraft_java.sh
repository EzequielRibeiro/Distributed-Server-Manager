#!/usr/bin/env bash
# Capivara DSM - Minecraft Java Vanilla resolver using Mojang's official version manifest.
set -Eeuo pipefail

MINECRAFT_JAVA_MANIFEST_URL="${MINECRAFT_JAVA_MANIFEST_URL:-https://piston-meta.mojang.com/mc/game/version_manifest_v2.json}"
MINECRAFT_JAVA_DISCOVERY_LIMIT="${MINECRAFT_JAVA_DISCOVERY_LIMIT:-50}"

minecraft_java_error(){ echo "[DSM][DISCOVERY][MINECRAFT-JAVA][ERROR] $*" >&2; }
minecraft_java_get(){ curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 "$1"; }

minecraft_java_manifest()
{
    minecraft_java_get "${MINECRAFT_JAVA_MANIFEST_URL}"
}

minecraft_java_list()
{
    local MANIFEST LIMIT
    MANIFEST="$(minecraft_java_manifest)" || return 1
    LIMIT="${MINECRAFT_JAVA_DISCOVERY_LIMIT}"
    [[ "${LIMIT}" =~ ^[0-9]+$ ]] || LIMIT=50
    (( LIMIT > 0 )) || LIMIT=50
    jq -c --argjson limit "${LIMIT}" '
      .latest.release as $latest |
      {
        game:"minecraft",
        variant:"vanilla",
        source:"mojang-version-manifest",
        versions:[
          .versions[]
          | select(.type=="release")
          | {
              version:(.id|tostring),
              build:(.id|tostring),
              minecraft_versions:[(.id|tostring)],
              stable:true,
              current:(.id==$latest),
              recommended:(.id==$latest)
            }
        ][0:$limit]
      }' <<<"${MANIFEST}"
}

minecraft_java_resolve()
{
    local SELECTOR="${1:-}" MANIFEST VERSION VERSION_URL META URL SHA1 SIZE
    [[ -n "${SELECTOR}" ]] || { minecraft_java_error "selector is required"; return 2; }
    MANIFEST="$(minecraft_java_manifest)" || return 1
    if [[ "${SELECTOR}" == "current" || "${SELECTOR}" == "latest" ]]; then
        VERSION="$(jq -r '.latest.release // empty' <<<"${MANIFEST}")"
    else
        VERSION="${SELECTOR%%@*}"
    fi
    [[ -n "${VERSION}" ]] || { minecraft_java_error "official manifest returned no latest release"; return 1; }
    VERSION_URL="$(jq -r --arg version "${VERSION}" '.versions[]? | select(.id==$version and .type=="release") | .url' <<<"${MANIFEST}" | head -n1)"
    if [[ -z "${VERSION_URL}" ]]; then
        jq -nc --arg selector "${SELECTOR}" '{error:"minecraft_java_version_not_found",selector:$selector}'
        return 1
    fi
    META="$(minecraft_java_get "${VERSION_URL}")" || return 1
    URL="$(jq -r '.downloads.server.url // empty' <<<"${META}")"
    SHA1="$(jq -r '.downloads.server.sha1 // empty' <<<"${META}")"
    SIZE="$(jq -r '.downloads.server.size // empty | tostring' <<<"${META}")"
    if [[ -z "${URL}" ]]; then
        jq -nc --arg version "${VERSION}" '{error:"minecraft_java_server_artifact_missing",version:$version}'
        return 1
    fi
    jq -nc       --arg version "${VERSION}"       --arg url "${URL}"       --arg sha1 "${SHA1}"       --arg size "${SIZE}" '
      {
        version:$version,
        build:$version,
        minecraft_versions:[$version],
        provider:"http",
        selected_asset:{
          name:"server.jar",
          url:$url,
          content_type:"application/java-archive",
          sha1:(if $sha1=="" then null else $sha1 end),
          size_bytes:(if $size=="" then null else ($size|tonumber) end)
        },
        install:{
          url:$url,
          asset:"server.jar"
        }
      }'
}

version_resolver_execute()
{
    local ACTION="${1:-}" SELECTOR="${4:-}"
    case "${ACTION}" in
        list) minecraft_java_list ;;
        resolve) minecraft_java_resolve "${SELECTOR}" ;;
        *) minecraft_java_error "unknown action: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
