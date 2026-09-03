#!/usr/bin/env bash
# Capivara DSM - Minecraft Forge resolver using the official Forge Maven repository.
set -Eeuo pipefail

FORGE_MAVEN_BASE="${FORGE_MAVEN_BASE:-https://maven.minecraftforge.net/net/minecraftforge/forge}"

forge_error(){ echo "[DSM][DISCOVERY][FORGE][ERROR] $*" >&2; }
forge_get(){ curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 "$1"; }

forge_versions()
{
    forge_get "${FORGE_MAVEN_BASE}/maven-metadata.xml" | python3 -c '
import sys, xml.etree.ElementTree as ET
root=ET.fromstring(sys.stdin.read())
for node in root.findall("./versioning/versions/version"):
    text=(node.text or "").strip()
    if text: print(text)
'
}

forge_pick()
{
    local MC_VERSION="$1" REQUESTED="${2:-}" FULL
    if [[ -n "${REQUESTED}" ]]; then
        if [[ "${REQUESTED}" == "${MC_VERSION}-"* ]]; then FULL="${REQUESTED}"; else FULL="${MC_VERSION}-${REQUESTED}"; fi
        forge_versions | grep -Fx -- "${FULL}" | tail -n1
    else
        forge_versions | grep -E "^${MC_VERSION//./\.}-" | tail -n1
    fi
}

forge_list()
{
    forge_versions | python3 -c '
import json,sys
versions=[]
for line in sys.stdin:
    full=line.strip()
    if "-" not in full: continue
    mc,build=full.split("-",1)
    versions.append({"version":mc,"build":build,"full":full,"minecraft_versions":[mc],"stable":True})
print(json.dumps({"game":"minecraft","variant":"forge","source":"forge-maven","versions":versions}))
'
}

forge_resolve()
{
    local SELECTOR="${1:-}" MC_VERSION REQUESTED FULL URL NAME SHA256
    [[ -n "${SELECTOR}" ]] || { forge_error "selector is required"; return 2; }
    IFS='@' read -r MC_VERSION REQUESTED <<<"${SELECTOR}"
    [[ "${MC_VERSION}" =~ ^[0-9]+\.[0-9]+([.][0-9]+)?$ ]] || { forge_error "invalid Minecraft version"; return 2; }
    FULL="$(forge_pick "${MC_VERSION}" "${REQUESTED:-}")"
    [[ -n "${FULL}" ]] || { jq -nc --arg selector "${SELECTOR}" '{error:"forge_version_not_found",selector:$selector}'; return 1; }
    NAME="forge-${FULL}-installer.jar"
    URL="${FORGE_MAVEN_BASE}/${FULL}/${NAME}"
    SHA256="$(forge_get "${URL}.sha256" | tr -d '\r\n ' | tr '[:upper:]' '[:lower:]')"
    [[ "${SHA256}" =~ ^[0-9a-f]{64}$ ]] || { forge_error "invalid SHA-256 metadata for ${FULL}"; return 1; }
    jq -nc --arg mc "${MC_VERSION}" --arg full "${FULL}" --arg url "${URL}" --arg name "${NAME}" --arg sha256 "${SHA256}" '
      {version:$mc,minecraft_versions:[$mc],build:$full,provider:"http",
       selected_asset:{name:$name,url:$url,sha256:$sha256,content_type:"application/java-archive"},
       install:{url:$url,asset:$name,sha256:$sha256}}'
}

version_resolver_execute()
{
    local ACTION="${1:-}" SELECTOR="${4:-}"
    case "${ACTION}" in
        list) forge_list ;;
        resolve) forge_resolve "${SELECTOR}" ;;
        *) forge_error "unknown action: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
