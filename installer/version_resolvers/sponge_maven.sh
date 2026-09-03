#!/usr/bin/env bash
# Capivara DSM - SpongeVanilla resolver using the official Sponge Maven repository.
set -Eeuo pipefail

SPONGE_MAVEN_BASE="${SPONGE_MAVEN_BASE:-https://repo.spongepowered.org/repository/maven-releases/org/spongepowered/spongevanilla}"

sponge_error(){ echo "[DSM][DISCOVERY][SPONGE][ERROR] $*" >&2; }
sponge_get(){ curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 "$1"; }

sponge_versions()
{
    sponge_get "${SPONGE_MAVEN_BASE}/maven-metadata.xml" | python3 -c '
import sys, xml.etree.ElementTree as ET
root=ET.fromstring(sys.stdin.read())
for node in root.findall("./versioning/versions/version"):
    text=(node.text or "").strip()
    if text: print(text)
'
}

sponge_pick()
{
    local MC_VERSION="$1" REQUESTED="${2:-}" FULL
    if [[ -n "${REQUESTED}" ]]; then
        if [[ "${REQUESTED}" == "${MC_VERSION}-"* ]]; then FULL="${REQUESTED}"; else FULL="${MC_VERSION}-${REQUESTED}"; fi
        sponge_versions | grep -Fx -- "${FULL}" | tail -n1
    else
        sponge_versions | grep -E "^${MC_VERSION//./\\.}-" | grep -Ev -- '-RC|-SNAPSHOT' | tail -n1
    fi
}

sponge_list()
{
    sponge_versions | python3 -c '
import json,sys,re
versions=[]
for line in sys.stdin:
    full=line.strip()
    match=re.match(r"^([0-9]+\.[0-9]+(?:\.[0-9]+)?)-(.+)$", full)
    if not match: continue
    mc,build=match.groups()
    versions.append({"version":mc,"build":build,"full":full,"minecraft_versions":[mc],"stable":("RC" not in build and "SNAPSHOT" not in build)})
print(json.dumps({"game":"minecraft","variant":"spongevanilla","source":"sponge-maven","versions":versions}))
'
}

sponge_resolve()
{
    local SELECTOR="${1:-}" MC_VERSION REQUESTED FULL REMOTE_NAME URL SHA256
    [[ -n "${SELECTOR}" ]] || { sponge_error "selector is required"; return 2; }
    IFS='@' read -r MC_VERSION REQUESTED <<<"${SELECTOR}"
    [[ "${MC_VERSION}" =~ ^[0-9]+\.[0-9]+([.][0-9]+)?$ ]] || { sponge_error "invalid Minecraft version"; return 2; }
    FULL="$(sponge_pick "${MC_VERSION}" "${REQUESTED:-}")"
    [[ -n "${FULL}" ]] || { jq -nc --arg selector "${SELECTOR}" '{error:"sponge_version_not_found",selector:$selector}'; return 1; }
    REMOTE_NAME="spongevanilla-${FULL}-universal.jar"
    URL="${SPONGE_MAVEN_BASE}/${FULL}/${REMOTE_NAME}"
    SHA256="$(sponge_get "${URL}.sha256" | tr -d '\r\n ' | tr '[:upper:]' '[:lower:]')"
    [[ "${SHA256}" =~ ^[0-9a-f]{64}$ ]] || { sponge_error "invalid SHA-256 metadata for ${FULL}"; return 1; }
    jq -nc --arg mc "${MC_VERSION}" --arg full "${FULL}" --arg url "${URL}" --arg sha256 "${SHA256}" '
      {version:$mc,minecraft_versions:[$mc],build:$full,provider:"http",
       selected_asset:{name:"server.jar",url:$url,sha256:$sha256,content_type:"application/java-archive"},
       install:{url:$url,asset:"server.jar",sha256:$sha256}}'
}

version_resolver_execute()
{
    local ACTION="${1:-}" SELECTOR="${4:-}"
    case "${ACTION}" in
        list) sponge_list ;;
        resolve) sponge_resolve "${SELECTOR}" ;;
        *) sponge_error "unknown action: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
