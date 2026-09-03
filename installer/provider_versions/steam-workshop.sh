#!/usr/bin/env bash
# Remote/local version adapter for Steam Workshop content.

workshop_version_parse_package()
{
    local PACKAGE="${1:-}"
    [[ "${PACKAGE}" =~ ^([0-9]+):([0-9]+)$ ]] || return 2
    printf '%s\t%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
}

provider_version()
{
    local PACKAGE="${1:-}" APP_ID ITEM_ID MANIFEST REV
    IFS=$'\t' read -r APP_ID ITEM_ID < <(workshop_version_parse_package "${PACKAGE}") || return $?
    MANIFEST="${STEAMCMD_ROOT}/steamapps/workshop/appworkshop_${APP_ID}.acf"
    [[ -f "${MANIFEST}" ]] || return 1

    REV="$(awk -v item="${ITEM_ID}" '
      index($0, "\"" item "\"") { in_item=1; next }
      in_item && /"timeupdated"/ {
        gsub(/"/, "", $2); print $2; exit
      }
      in_item && /^\s*}/ { in_item=0 }
    ' "${MANIFEST}")"
    [[ "${REV}" =~ ^[0-9]+$ ]] || return 1
    printf '%s\n' "${REV}"
}

provider_remote_version()
{
    local PACKAGE="${1:-}" APP_ID ITEM_ID RESPONSE REV
    IFS=$'\t' read -r APP_ID ITEM_ID < <(workshop_version_parse_package "${PACKAGE}") || return $?
    command -v curl >/dev/null 2>&1 || return 1
    command -v jq >/dev/null 2>&1 || return 1

    RESPONSE="$(curl --silent --show-error --fail --location \
      --connect-timeout 10 --max-time 30 \
      --data-urlencode 'itemcount=1' \
      --data-urlencode "publishedfileids[0]=${ITEM_ID}" \
      'https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/' 2>/dev/null)" || return 1

    REV="$(jq -r '.response.publishedfiledetails[0].time_updated // empty' <<<"${RESPONSE}")"
    [[ "${REV}" =~ ^[0-9]+$ ]] || return 1
    printf '%s\n' "${REV}"
}

export -f workshop_version_parse_package provider_version provider_remote_version
