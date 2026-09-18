#!/usr/bin/env bash

# Load only the Steam account name required by non-interactive SteamCMD workers.
# The provider config is data, not shell code: never source or eval it here.
load_worker_steam_user()
{
    local ROOT="${1:-${DSM_ROOT:-/opt/dsm}}"
    local CONF="${ROOT}/config/providers/steam.conf"
    local LINE=""
    local VALUE=""

    [[ -r "${CONF}" ]] || return 0

    while IFS= read -r LINE || [[ -n "${LINE}" ]]
    do
        if [[ "${LINE}" =~ ^[[:space:]]*DSM_STEAM_USER[[:space:]]*=[[:space:]]*(.*)[[:space:]]*$ ]]
        then
            VALUE="${BASH_REMATCH[1]}"
            VALUE="${VALUE%$'\r'}"

            if [[ "${VALUE}" =~ ^\"([^\"]*)\"$ ]]
            then
                VALUE="${BASH_REMATCH[1]}"
            elif [[ "${VALUE}" =~ ^\'([^\']*)\'$ ]]
            then
                VALUE="${BASH_REMATCH[1]}"
            fi

            # Steam account names are passed as one argv element. Reject shell
            # syntax, whitespace, comments and control characters fail-closed.
            if [[ ! "${VALUE}" =~ ^[A-Za-z0-9_.@-]+$ ]]
            then
                printf '[DSM][STEAM][ERRO] DSM_STEAM_USER inválido em %s\n' "${CONF}" >&2
                return 1
            fi

            export DSM_STEAM_USER="${VALUE}"
            return 0
        fi
    done < "${CONF}"

    return 0
}
