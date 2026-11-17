#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

export DSM_ROOT="${ROOT}"
# shellcheck source=/dev/null
source "${ROOT}/installer/providers/steam-workshop.sh"

# Replace only the external SteamCMD boundary. The provider logic, parsing,
# staging copy and metadata generation remain the production implementation.
mkdir -p "${TMP}/agent-state" "${TMP}/authenticated-home"
export CAPIVARA_AGENT_STATE_DIR="${TMP}/agent-state"
export HOME="${TMP}/authenticated-home"
export CAPIVARA_STEAM_HOME="$HOME"
export XDG_DATA_HOME="${HOME}/.local/share"
STEAMCMD_ROOT="${TMP}/steamcmd"
STEAMCMD_BIN="${TMP}/steamcmd/steamcmd.sh"
mkdir -p "${STEAMCMD_ROOT}"
printf '#!/usr/bin/env bash\nexit 0\n' >"${STEAMCMD_BIN}"
chmod +x "${STEAMCMD_BIN}"

steam_provider_validate(){ return 0; }
steam_progress_publish(){ :; }
steamcmd_run_with_progress()
{
    local APP="" ITEM="" PREV=""
    [[ "$HOME" == "${CAPIVARA_AGENT_STATE_DIR}/steam-anonymous-install-home" ]] || return 11
    [[ "$XDG_DATA_HOME" == "${HOME}/.local/share" ]] || return 12
    for ARG in "$@"; do
        if [[ "${PREV}" == "+workshop_download_item" ]]; then APP="${ARG}"; PREV="workshop-app"; continue; fi
        if [[ "${PREV}" == "workshop-app" ]]; then ITEM="${ARG}"; PREV=""; continue; fi
        PREV="${ARG}"
    done
    [[ "${APP}" == "221100" && "${ITEM}" == "1559212036" ]] || return 9
    mkdir -p "${STEAMCMD_ROOT}/steamapps/workshop/content/${APP}/${ITEM}/Keys"
    printf 'fixture' >"${STEAMCMD_ROOT}/steamapps/workshop/content/${APP}/${ITEM}/mod.cpp"
    printf 'key' >"${STEAMCMD_ROOT}/steamapps/workshop/content/${APP}/${ITEM}/Keys/example.bikey"
}

DEST="${TMP}/installed"
workshop_provider_install "221100:1559212036" "${DEST}" anonymous
[[ "$(stat -c '%a' "${CAPIVARA_AGENT_STATE_DIR}/steam-anonymous-install-home")" == "700" ]]
[[ "$HOME" == "${TMP}/authenticated-home" ]]
[[ -f "${DEST}/mod.cpp" ]]
[[ -f "${DEST}/Keys/example.bikey" ]]
jq -e '.kind=="SteamWorkshopArtifact" and .workshop_app_id=="221100" and .published_file_id=="1559212036"' \
    "${DEST}/.dsm/workshop.json" >/dev/null
workshop_provider_verify "221100:1559212036" "${DEST}"

export DSM_WORKSHOP_APP_ID=108600
export DSM_WORKSHOP_ITEM_ID=123456789
PARSED="$(workshop_parse_package ignored)"
[[ "${PARSED}" == $'108600\t123456789' ]]
unset DSM_WORKSHOP_APP_ID DSM_WORKSHOP_ITEM_ID

if workshop_parse_package '221100;rm -rf /' >/dev/null 2>&1; then
    echo 'FAIL: unsafe Workshop package accepted' >&2
    exit 1
fi

# Simulate a zero-exit unauthenticated login; no Workshop action is allowed.
cat > "${STEAMCMD_BIN}" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' 'Waiting for user info...OK' 'ACCOUNT_TOKEN=NEVER_EXPOSE'
exit 0
MOCK
chmod +x "${STEAMCMD_BIN}"
set +e
AUTH_RESULT="$(workshop_provider_install '221100:1559212036' "${TMP}/auth-blocked" steam-test-user 2>&1)"
AUTH_RC=$?
set -e
[[ "$AUTH_RC" == 42 ]]
[[ "$AUTH_RESULT" != *NEVER_EXPOSE* ]]
[[ ! -d "${TMP}/auth-blocked" ]]
# Detect and refuse a session associated with a different Steam account.
cat > "${STEAMCMD_BIN}" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "Logging in user 'anonymous' to Steam Public...OK" 'Logged in OK'
exit 0
MOCK
chmod +x "${STEAMCMD_BIN}"
set +e
AUTH_RESULT="$(workshop_provider_install '221100:1559212036' "${TMP}/auth-wrong-user" steam-test-user 2>&1)"
AUTH_RC=$?
set -e
[[ "$AUTH_RC" == 42 ]]
[[ ! -d "${TMP}/auth-wrong-user" ]]
# Fail before SteamCMD launch if the anonymous HOME is a symlink.
rm -rf -- "${CAPIVARA_AGENT_STATE_DIR}/steam-anonymous-install-home"
ln -s -- "${HOME}" "${CAPIVARA_AGENT_STATE_DIR}/steam-anonymous-install-home"
set +e
ANON_RESULT="$(workshop_provider_install '221100:1559212036' "${TMP}/redirect-blocked" anonymous 2>&1)"
ANON_RC=$?
set -e
[[ "$ANON_RC" != 0 ]]
[[ ! -d "${TMP}/redirect-blocked" ]]

echo 'Steam Workshop content provider tests passed.'
