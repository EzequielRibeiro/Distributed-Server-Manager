#!/usr/bin/env bash
# Capivara DSM - Minecraft NeoForge resolver using the official NeoForged Maven repository.
set -Eeuo pipefail

NEOFORGE_MAVEN_BASE="${NEOFORGE_MAVEN_BASE:-https://maven.neoforged.net/releases/net/neoforged/neoforge}"

neoforge_error(){ echo "[DSM][DISCOVERY][NEOFORGE][ERROR] $*" >&2; }
neoforge_get(){ curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 "$1"; }

neoforge_versions()
{
    neoforge_get "${NEOFORGE_MAVEN_BASE}/maven-metadata.xml" | python3 -c '
import sys, xml.etree.ElementTree as ET
root=ET.fromstring(sys.stdin.read())
for node in root.findall("./versioning/versions/version"):
    text=(node.text or "").strip()
    if text: print(text)
'
}

neoforge_prefix()
{
    local MC_VERSION="$1"
    if [[ "${MC_VERSION}" =~ ^1\.([0-9]+)\.([0-9]+)$ ]]; then
        printf '%s.%s.' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    elif [[ "${MC_VERSION}" =~ ^1\.([0-9]+)$ ]]; then
        printf '%s.' "${BASH_REMATCH[1]}"
    else
        printf '%s.' "${MC_VERSION}"
    fi
}

neoforge_pick()
{
    local MC_VERSION="$1" REQUESTED="${2:-}" PREFIX
    if [[ -n "${REQUESTED}" ]]; then
        neoforge_versions | grep -Fx -- "${REQUESTED}" | tail -n1
    else
        PREFIX="$(neoforge_prefix "${MC_VERSION}")"
        neoforge_versions | grep -E "^${PREFIX//./\.}[0-9]" | tail -n1
    fi
}

neoforge_list()
{
    neoforge_versions | python3 -c '
import json,sys,re
versions=[]
for line in sys.stdin:
    value=line.strip()
    if not value: continue
    parts=value.split(".")
    if len(parts)<3: continue
    if parts[0].isdigit() and int(parts[0]) < 26:
        mc=f"1.{parts[0]}.{parts[1]}"
    else:
        mc=".".join(parts[:-1])
    versions.append({"version":mc,"build":value,"minecraft_versions":[mc],"stable":True})
print(json.dumps({"game":"minecraft","variant":"neoforge","source":"neoforge-maven","versions":versions}))
'
}

neoforge_resolve()
{
    local SELECTOR="${1:-}" MC_VERSION REQUESTED VERSION URL NAME SHA256
    [[ -n "${SELECTOR}" ]] || { neoforge_error "selector is required"; return 2; }
    IFS='@' read -r MC_VERSION REQUESTED <<<"${SELECTOR}"
    [[ "${MC_VERSION}" =~ ^[0-9]+\.[0-9]+([.][0-9]+)?$ ]] || { neoforge_error "invalid Minecraft version"; return 2; }
    VERSION="$(neoforge_pick "${MC_VERSION}" "${REQUESTED:-}")"
    [[ -n "${VERSION}" ]] || { jq -nc --arg selector "${SELECTOR}" '{error:"neoforge_version_not_found",selector:$selector}'; return 1; }
    NAME="neoforge-${VERSION}-installer.jar"
    URL="${NEOFORGE_MAVEN_BASE}/${VERSION}/${NAME}"
    SHA256="$(neoforge_get "${URL}.sha256" | tr -d '\r\n ' | tr '[:upper:]' '[:lower:]')"
    [[ "${SHA256}" =~ ^[0-9a-f]{64}$ ]] || { neoforge_error "invalid SHA-256 metadata for ${VERSION}"; return 1; }
    jq -nc --arg mc "${MC_VERSION}" --arg build "${VERSION}" --arg url "${URL}" --arg name "${NAME}" --arg sha256 "${SHA256}" '
      {version:$mc,minecraft_versions:[$mc],build:$build,provider:"http",
       selected_asset:{name:$name,url:$url,sha256:$sha256,content_type:"application/java-archive"},
       install:{url:$url,asset:$name,sha256:$sha256}}'
}

version_resolver_execute()
{
    local ACTION="${1:-}" SELECTOR="${4:-}"
    case "${ACTION}" in
        list) neoforge_list ;;
        resolve) neoforge_resolve "${SELECTOR}" ;;
        *) neoforge_error "unknown action: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
