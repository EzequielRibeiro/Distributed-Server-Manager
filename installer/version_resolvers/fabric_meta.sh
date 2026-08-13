#!/usr/bin/env bash
# =============================================================
# Capivara DSM - Fabric Meta Version Resolver v1
#
# Uses the official Fabric Meta API:
#   https://meta.fabricmc.net/v2/versions/game
#   https://meta.fabricmc.net/v2/versions/loader/<mc>
#   https://meta.fabricmc.net/v2/versions/installer
#   https://meta.fabricmc.net/v2/versions/loader/<mc>/<loader>/<installer>/server/jar
#
# Selector formats:
#   1.21.1             -> latest stable loader + latest stable installer
#   1.21.1@0.16.14     -> requested loader + latest stable installer
#   1.21.1@0.16.14@1.0.3 -> requested loader + requested installer
# =============================================================
set -Eeuo pipefail

FABRIC_META_BASE="${FABRIC_META_BASE:-https://meta.fabricmc.net/v2}"

fabric_error(){ echo "[DSM][DISCOVERY][FABRIC][ERRO] $*" >&2; }

fabric_get()
{
    local URL="${1:-}"
    [[ -n "${URL}" ]] || return 2
    curl --fail --silent --show-error --location \
         --connect-timeout 15 --max-time 45 \
         "${URL}"
}

fabric_list()
{
    local RAW
    RAW="$(fabric_get "${FABRIC_META_BASE}/versions/game")" || return 1

    jq -c --arg game "${GAME_ID:-minecraft}" --arg variant "${VARIANT_ID:-fabric}" '
      {
        game:$game,
        variant:$variant,
        source:"fabric-meta",
        versions:[
          .[] |
          select(.stable == true) |
          {
            version:.version,
            minecraft_versions:[.version],
            stable:(.stable // false)
          }
        ]
      }' <<<"${RAW}"
}

fabric_pick_loader()
{
    local MC_VERSION="$1"
    local REQUESTED="${2:-}"
    local RAW

    RAW="$(fabric_get "${FABRIC_META_BASE}/versions/loader/${MC_VERSION}")" || return 1

    if [[ -n "${REQUESTED}" ]]
    then
        jq -c --arg v "${REQUESTED}" '
          map(select(.loader.version == $v)) | first // empty' <<<"${RAW}"
    else
        jq -c '
          map(select((.loader.stable // false) == true)) | first // first // empty' <<<"${RAW}"
    fi
}

fabric_pick_installer()
{
    local REQUESTED="${1:-}"
    local RAW

    RAW="$(fabric_get "${FABRIC_META_BASE}/versions/installer")" || return 1

    if [[ -n "${REQUESTED}" ]]
    then
        jq -c --arg v "${REQUESTED}" 'map(select(.version == $v)) | first // empty' <<<"${RAW}"
    else
        jq -c 'map(select((.stable // false) == true)) | first // first // empty' <<<"${RAW}"
    fi
}

fabric_resolve()
{
    local SELECTOR="${1:-}"
    local MC_VERSION LOADER_VERSION INSTALLER_VERSION
    local LOADER_JSON INSTALLER_JSON URL FILE_NAME

    [[ -n "${SELECTOR}" ]] || { fabric_error "Selector não informado."; return 2; }

    IFS='@' read -r MC_VERSION LOADER_VERSION INSTALLER_VERSION <<<"${SELECTOR}"
    [[ -n "${MC_VERSION}" ]] || { fabric_error "Minecraft version inválida."; return 2; }

    LOADER_JSON="$(fabric_pick_loader "${MC_VERSION}" "${LOADER_VERSION:-}")" || return 1
    [[ -n "${LOADER_JSON}" ]] || {
        jq -nc --arg selector "${SELECTOR}" '{error:"loader_not_found",selector:$selector}'
        return 1
    }

    LOADER_VERSION="$(jq -r '.loader.version' <<<"${LOADER_JSON}")"

    INSTALLER_JSON="$(fabric_pick_installer "${INSTALLER_VERSION:-}")" || return 1
    [[ -n "${INSTALLER_JSON}" ]] || {
        jq -nc --arg selector "${SELECTOR}" '{error:"installer_not_found",selector:$selector}'
        return 1
    }

    INSTALLER_VERSION="$(jq -r '.version' <<<"${INSTALLER_JSON}")"

    URL="${FABRIC_META_BASE}/versions/loader/${MC_VERSION}/${LOADER_VERSION}/${INSTALLER_VERSION}/server/jar"
    FILE_NAME="fabric-server-mc.${MC_VERSION}-loader.${LOADER_VERSION}-launcher.${INSTALLER_VERSION}.jar"

    jq -nc \
      --arg mc "${MC_VERSION}" \
      --arg loader "${LOADER_VERSION}" \
      --arg installer "${INSTALLER_VERSION}" \
      --arg url "${URL}" \
      --arg name "${FILE_NAME}" '
      {
        version:$mc,
        minecraft_versions:[$mc],
        loader:$loader,
        installer:$installer,
        build:("loader-"+$loader+"_installer-"+$installer),
        provider:"http",
        selected_asset:{
          name:$name,
          url:$url,
          content_type:"application/java-archive"
        },
        install:{
          url:$url,
          asset:$name
        }
      }'
}

version_resolver_execute()
{
    local ACTION="${1:-}"
    local GAME="${2:-}"
    local VARIANT="${3:-}"
    local SELECTOR="${4:-}"

    case "${ACTION}" in
        list) fabric_list ;;
        resolve) fabric_resolve "${SELECTOR}" ;;
        *) fabric_error "Ação desconhecida: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
