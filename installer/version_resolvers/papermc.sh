#!/usr/bin/env bash
# =============================================================
# Capivara DSM - PaperMC Version Resolver v2
#
# API oficial: https://fill.papermc.io/v3
# Seletores:
#   1.21.11       -> build STABLE mais recente
#   1.21.11@48    -> build específico
# =============================================================
set -Eeuo pipefail

PAPERMC_API_BASE="${PAPERMC_API_BASE:-https://fill.papermc.io/v3}"
PAPERMC_PROJECT="${PAPERMC_PROJECT:-paper}"
PAPERMC_USER_AGENT="${PAPERMC_USER_AGENT:-Capivara-DSM/1.0 (https://github.com/EzequielRibeiro/capivara-dsm)}"

paper_error(){ echo "[DSM][DISCOVERY][PAPER][ERRO] $*" >&2; }

paper_get()
{
    local URL="${1:-}"
    [[ -n "${URL}" ]] || return 2

    curl --fail --silent --show-error --location --connect-timeout 15 --max-time 45 \
        --header "User-Agent: ${PAPERMC_USER_AGENT}" \
        --header "Accept: application/json" \
        "${URL}"
}

paper_list()
{
    local RAW
    RAW="$(paper_get "${PAPERMC_API_BASE}/projects/${PAPERMC_PROJECT}")" || return 1

    jq -c --arg game "${GAME_ID:-minecraft}" --arg variant "${VARIANT_ID:-paper}" --arg project "${PAPERMC_PROJECT}" '
      [.versions | to_entries[] | .value[]] |
      unique |
      sort_by(split(".") | map(tonumber? // 0)) |
      reverse |
      {game:$game,variant:$variant,source:"papermc-fill-v3",project:$project,
       versions:map({version:.,minecraft_versions:[.],provider:"http"})}' <<<"${RAW}"
}

paper_parse_selector()
{
    local SELECTOR="${1:-}" VERSION BUILD
    VERSION="${SELECTOR%%@*}"
    BUILD=""
    if [[ "${SELECTOR}" == *"@"* ]]; then BUILD="${SELECTOR#*@}"; fi
    [[ -n "${VERSION}" ]] || return 1
    printf '%s\t%s\n' "${VERSION}" "${BUILD}"
}

paper_resolve()
{
    local SELECTOR="${1:-}" VERSION BUILD RAW SELECTED
    IFS=$'\t' read -r VERSION BUILD < <(paper_parse_selector "${SELECTOR}") || {
        paper_error "Seletor inválido: ${SELECTOR}"
        return 1
    }

    RAW="$(paper_get "${PAPERMC_API_BASE}/projects/${PAPERMC_PROJECT}/versions/${VERSION}/builds")" || return 1
    if jq -e '.ok == false' >/dev/null 2>&1 <<<"${RAW}"; then
        jq -c '{error:"papermc_api_error",message:(.message // "unknown")}' <<<"${RAW}"
        return 1
    fi

    if [[ -n "${BUILD}" ]]; then
        SELECTED="$(jq -c --arg build "${BUILD}" 'map(select((.id|tostring)==$build or (.number?|tostring)==$build)) | first // empty' <<<"${RAW}")"
    else
        SELECTED="$(jq -c '(map(select(.channel == "STABLE")) | first) // empty' <<<"${RAW}")"
    fi

    if [[ -z "${SELECTED}" || "${SELECTED}" == "null" ]]; then
        jq -nc --arg version "${VERSION}" --arg build "${BUILD}" '{error:"build_not_found",version:$version,build:(if $build=="" then "latest-stable" else $build end)}'
        return 1
    fi

    jq -c --arg game "${GAME_ID:-minecraft}" --arg variant "${VARIANT_ID:-paper}" --arg version "${VERSION}" --arg project "${PAPERMC_PROJECT}" '
      (.downloads."server:default" // null) as $download |
      if $download == null then
        {error:"download_not_found",version:$version,build:(.id // .number // null)}
      else
        {
          game:$game, variant:$variant, source:"papermc-fill-v3", project:$project,
          version:$version, minecraft_versions:[$version], build:(.id // .number),
          channel:(.channel // "UNKNOWN"), provider:"http",
          selected_asset:{
            name:"server.jar",
            upstream_name:($download.name // ($project + ".jar")),
            size:($download.size // 0),
            url:$download.url,
            content_type:"application/java-archive",
            sha256:($download.checksums.sha256 // null)
          },
          install:{
            url:$download.url,
            asset:"server.jar",
            upstream_asset:($download.name // ($project + ".jar")),
            sha256:($download.checksums.sha256 // null)
          }
        }
      end' <<<"${SELECTED}"
}

version_resolver_execute()
{
    local ACTION="${1:-}" GAME="${2:-}" VARIANT="${3:-}" SELECTOR="${4:-}"
    case "${ACTION}" in
        list) paper_list ;;
        resolve) paper_resolve "${SELECTOR}" ;;
        *) paper_error "Ação desconhecida: ${ACTION}"; return 2 ;;
    esac
}

export -f version_resolver_execute
