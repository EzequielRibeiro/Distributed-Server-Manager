#!/usr/bin/env bash
# Remote-version adapter for the canonical Steam provider.

provider_remote_version()
{
    local APP_ID="${1:-}" OUTPUT BUILD
    [[ "${APP_ID}" =~ ^[0-9]+$ ]] || return 2
    [[ -x "${STEAMCMD_BIN:-}" ]] || steam_provider_validate || return 1

    # A metadata-only anonymous login must never reuse the Agent's authenticated
    # HOME. Keep this separate from both installs and interactive Steam auth.
    local STATE_ROOT="${CAPIVARA_AGENT_STATE_DIR:-${DSM_ROOT:-/opt/dsm}/runtime/hybrid-agent-state}"
    local ANON_HOME="${STATE_ROOT}/steam-anonymous-metadata-home"
    [[ ! -L "${STATE_ROOT}" && ! -L "${ANON_HOME}" ]] || return 1
    [[ -d "${STATE_ROOT}" && -O "${STATE_ROOT}" ]] || return 1
    if [[ ! -e "${ANON_HOME}" ]]; then
        (umask 077; mkdir -m 700 -- "${ANON_HOME}") || return 1
    fi
    [[ -d "${ANON_HOME}" && ! -L "${ANON_HOME}" && -O "${ANON_HOME}" ]] || return 1
    [[ "$(stat -c '%a' -- "${ANON_HOME}")" == "700" ]] || return 1

    OUTPUT="$(HOME="${ANON_HOME}" XDG_DATA_HOME="${ANON_HOME}/.local/share" \
        CAPIVARA_STEAM_HOME="${ANON_HOME}" \
        "${STEAMCMD_BIN}" +login anonymous +app_info_update 1 +app_info_print "${APP_ID}" +quit 2>/dev/null)" || return 1
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
