#!/usr/bin/env bash
# Remote-version adapter for the canonical Steam provider.

provider_remote_version()
{
    local APP_ID="${1:-}" OUTPUT BUILD
    [[ "${APP_ID}" =~ ^[0-9]+$ ]] || return 2
    [[ -x "${STEAMCMD_BIN:-}" ]] || steam_provider_validate || return 1

    OUTPUT="$("${STEAMCMD_BIN}" +login anonymous +app_info_update 1 +app_info_print "${APP_ID}" +quit 2>/dev/null)" || return 1
    BUILD="$(awk '
      /"branches"/ { in_branches=1; next }
      in_branches && /"public"/ { in_public=1; next }
      in_public && /"buildid"/ {
        gsub(/"/, "", $2); print $2; exit
      }
      in_public && /^\s*}/ { in_public=0 }
    ' <<<"${OUTPUT}")"
    [[ "${BUILD}" =~ ^[0-9]+$ ]] || return 1
    printf '%s\n' "${BUILD}"
}

export -f provider_remote_version
