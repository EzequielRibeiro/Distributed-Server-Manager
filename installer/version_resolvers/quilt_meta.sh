#!/usr/bin/env bash
# Capivara DSM - Quilt Meta resolver
set -Eeuo pipefail

QUILT_META_BASE="${QUILT_META_BASE:-https://meta.quiltmc.org/v3}"
QUILT_USER_AGENT="${QUILT_USER_AGENT:-Capivara-DSM/1.0}"

quilt_get()
{
    local url="${1:-}"
    [[ -n "${url}" ]] || return 2
    curl --fail --silent --show-error --location \
        --connect-timeout 15 --max-time 45 \
        --header "User-Agent: ${QUILT_USER_AGENT}" \
        --header "Accept: application/json" \
        "${url}"
}

quilt_list()
{
    local games
    games="$(quilt_get "${QUILT_META_BASE}/versions/game")" || return 1
    jq -c --arg game "${GAME_ID:-minecraft}" --arg variant "${VARIANT_ID:-quilt}" '
      {
        game:$game,
        variant:$variant,
        source:"quilt-meta-v3",
        versions:[.[] | select(.stable == true) | {version:.version,minecraft_versions:[.version],provider:"http"}]
      }' <<<"${games}"
}

quilt_resolve()
{
    local version="${1:-}" games installers selected
    [[ -n "${version}" ]] || { echo "[DSM][DISCOVERY][QUILT][ERRO] versão ausente" >&2; return 1; }
    [[ "${version}" =~ ^[A-Za-z0-9._+-]{1,64}$ ]] || { echo "[DSM][DISCOVERY][QUILT][ERRO] versão inválida" >&2; return 1; }

    games="$(quilt_get "${QUILT_META_BASE}/versions/game")" || return 1
    jq -e --arg version "${version}" 'any(.[]; .version == $version and .stable == true)' <<<"${games}" >/dev/null \
        || { jq -nc --arg version "${version}" '{error:"unsupported_quilt_game_version",version:$version}'; return 1; }

    installers="$(quilt_get "${QUILT_META_BASE}/versions/installer")" || return 1
    selected="$(jq -c 'first // empty' <<<"${installers}")"
    [[ -n "${selected}" && "${selected}" != "null" ]] \
        || { jq -nc '{error:"quilt_installer_not_found"}'; return 1; }

    jq -c --arg game "${GAME_ID:-minecraft}" --arg variant "${VARIANT_ID:-quilt}" --arg version "${version}" '
      (.hashes.sha256 // null) as $sha |
      if (.url|type)!="string" or (.url|startswith("https://maven.quiltmc.org/")|not) or ($sha|type)!="string" or ($sha|test("^[0-9a-f]{64}$")|not) then
        {error:"invalid_quilt_installer_metadata"}
      else
        {
          game:$game,
          variant:$variant,
          source:"quilt-meta-v3",
          version:$version,
          minecraft_versions:[$version],
          build:.version,
          provider:"http",
          selected_asset:{
            name:"quilt-installer.jar",
            upstream_name:("quilt-installer-" + .version + ".jar"),
            size:(.file_size // 0),
            url:.url,
            content_type:"application/java-archive",
            sha256:$sha
          },
          install:{
            url:.url,
            asset:"quilt-installer.jar",
            upstream_asset:("quilt-installer-" + .version + ".jar"),
            sha256:$sha
          }
        }
      end' <<<"${selected}"
}

version_resolver_execute()
{
    local action="${1:-}" game="${2:-}" variant="${3:-}" selector="${4:-}"
    case "${action}" in
        list) quilt_list ;;
        resolve) quilt_resolve "${selector}" ;;
        *) echo "[DSM][DISCOVERY][QUILT][ERRO] ação desconhecida: ${action}" >&2; return 2 ;;
    esac
}

export -f version_resolver_execute
