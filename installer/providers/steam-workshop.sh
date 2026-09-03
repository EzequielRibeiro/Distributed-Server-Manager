#!/usr/bin/env bash
# Capivara DSM - Generic Steam Workshop content provider
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
# Reuse the canonical SteamCMD bootstrap, authentication and progress runner.
# shellcheck source=/dev/null
source "${DSM_ROOT}/installer/providers/steam.sh"

workshop_log(){ echo "[DSM][WORKSHOP] $*"; }
workshop_error(){ echo "[DSM][WORKSHOP][ERROR] $*" >&2; }

workshop_parse_package()
{
    local PACKAGE="${1:-}" APP_ID ITEM_ID
    APP_ID="${DSM_WORKSHOP_APP_ID:-}"
    ITEM_ID="${DSM_WORKSHOP_ITEM_ID:-}"

    if [[ -z "${APP_ID}" || -z "${ITEM_ID}" ]]; then
        if [[ "${PACKAGE}" =~ ^([0-9]+):([0-9]+)$ ]]; then
            APP_ID="${BASH_REMATCH[1]}"
            ITEM_ID="${BASH_REMATCH[2]}"
        fi
    fi

    [[ "${APP_ID}" =~ ^[0-9]+$ ]] || { workshop_error "Invalid Workshop AppID."; return 2; }
    [[ "${ITEM_ID}" =~ ^[0-9]+$ ]] || { workshop_error "Invalid PublishedFileId."; return 2; }
    printf '%s\t%s\n' "${APP_ID}" "${ITEM_ID}"
}

workshop_cache_path()
{
    printf '%s/steamapps/workshop/content/%s/%s\n' "${STEAMCMD_ROOT}" "$1" "$2"
}

workshop_login_args()
{
    local USER="${1:-anonymous}"
    if [[ -z "${USER}" || "${USER}" == "anonymous" ]]; then
        printf '%s\n' anonymous
    else
        printf '%s\n' "${USER}"
    fi
}

workshop_provider_install()
{
    local PACKAGE="${1:-}" INSTALL_PATH="${2:-}" STEAM_USER="${3:-anonymous}"
    local APP_ID ITEM_ID SOURCE LOGIN

    [[ -n "${INSTALL_PATH}" ]] || { workshop_error "Install path is required."; return 2; }
    IFS=$'\t' read -r APP_ID ITEM_ID < <(workshop_parse_package "${PACKAGE}") || return $?

    steam_provider_validate || return 1
    LOGIN="$(workshop_login_args "${STEAM_USER}")"

    if [[ "${LOGIN}" != "anonymous" ]]; then
        # Fail fast when the cached Steam session is missing/expired. Credentials
        # are never supplied by this provider.
        local AUTH_STATUS=0
        if command -v timeout >/dev/null 2>&1; then
            timeout 60 "${STEAMCMD_BIN}" +login "${LOGIN}" +quit </dev/null >/dev/null 2>&1 || AUTH_STATUS=$?
        else
            "${STEAMCMD_BIN}" +login "${LOGIN}" +quit </dev/null >/dev/null 2>&1 || AUTH_STATUS=$?
        fi
        if (( AUTH_STATUS != 0 )); then
            workshop_error "Steam authentication required. Run 'dsm steam auth' on the Agent."
            return 42
        fi
    fi

    workshop_log "AppID=${APP_ID} PublishedFileId=${ITEM_ID}"
    steamcmd_run_with_progress \
        +login "${LOGIN}" \
        +workshop_download_item "${APP_ID}" "${ITEM_ID}" validate \
        +quit || return 1

    SOURCE="$(workshop_cache_path "${APP_ID}" "${ITEM_ID}")"
    [[ -d "${SOURCE}" ]] || {
        workshop_error "SteamCMD completed but Workshop item is missing: ${SOURCE}"
        return 1
    }

    mkdir -p "${INSTALL_PATH}"
    cp -a -- "${SOURCE}/." "${INSTALL_PATH}/"

    # Provider metadata is intentionally generic. Game-specific activation is
    # handled by content adapters, not by the Workshop downloader.
    mkdir -p "${INSTALL_PATH}/.dsm"
    jq -n \
        --arg app_id "${APP_ID}" \
        --arg published_file_id "${ITEM_ID}" \
        '{schema_version:1,kind:"SteamWorkshopArtifact",workshop_app_id:$app_id,published_file_id:$published_file_id}' \
        >"${INSTALL_PATH}/.dsm/workshop.json"

    steam_progress_publish 100
}

workshop_provider_verify()
{
    local PACKAGE="${1:-}" INSTALL_PATH="${2:-}" APP_ID ITEM_ID META
    IFS=$'\t' read -r APP_ID ITEM_ID < <(workshop_parse_package "${PACKAGE}") || return $?
    META="${INSTALL_PATH}/.dsm/workshop.json"
    [[ -f "${META}" ]] || return 1
    jq -e --arg app "${APP_ID}" --arg item "${ITEM_ID}" \
        '.kind=="SteamWorkshopArtifact" and .workshop_app_id==$app and .published_file_id==$item' \
        "${META}" >/dev/null
}

provider_ensure(){ steam_provider_ensure; }
provider_install(){ workshop_provider_install "$@"; }
provider_update(){ workshop_provider_install "$@"; }
provider_verify(){ workshop_provider_verify "$@"; }
provider_info(){ echo "provider=steam-workshop"; }
provider_version(){ printf '%s\n' "${DSM_WORKSHOP_ITEM_ID:-unknown}"; }

export DSM_PROVIDER_API_VERSION=1
export DSM_PROVIDER_KIND=content
export DSM_PROVIDER_NAME=steam-workshop
export -f workshop_log workshop_error workshop_parse_package workshop_cache_path
export -f workshop_provider_install workshop_provider_verify
export -f provider_ensure provider_install provider_update provider_verify provider_info provider_version
