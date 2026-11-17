#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export DSM_ROOT="$TMP"
source "$ROOT/installer/providers/steam.sh"
STEAMCMD_BIN="$TMP/steamcmd-mock"
cat > "$STEAMCMD_BIN" <<'MOCK'
#!/bin/sh
printf '%s\n' 'Session secret=DO_NOT_EXPOSE' 'Update state (0x61) downloading, progress: 42.00 (42 / 100)' 
exit 27
MOCK
chmod +x "$STEAMCMD_BIN"
set +e
OUTPUT="$(steamcmd_run_with_progress +login test +app_update 223350 validate +quit 2>&1)"
STATUS=$?
set -e
[[ "$STATUS" -eq 27 ]]
[[ "$OUTPUT" != *DO_NOT_EXPOSE* ]]
[[ "$OUTPUT" == *'código 27'* ]]
! grep -q DO_NOT_EXPOSE "$STEAMCMD_PROGRESS_LOG"
# Anonymous installations use an isolated HOME even through the progress PTY.
mkdir -p "${TMP}/agent-state" "${TMP}/authenticated-home"
export CAPIVARA_AGENT_STATE_DIR="${TMP}/agent-state"
export HOME="${TMP}/authenticated-home"
export XDG_DATA_HOME="${TMP}/authenticated-home/.local/share"
cat > "${STEAMCMD_BIN}" <<'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$HOME" > "$DSM_STEAM_TEST_MARKER"
printf '%s\n' "$XDG_DATA_HOME" > "${DSM_STEAM_TEST_MARKER}.xdg"
case "$*" in *'+login anonymous'*) exit 0 ;; *) exit 42 ;; esac
MOCK
chmod +x "${STEAMCMD_BIN}"
export DSM_STEAM_TEST_MARKER="${TMP}/anonymous-run-home"
steam_provider_install_anonymous 223350 "${TMP}/anonymous-install" >/dev/null
[[ "$(cat "${DSM_STEAM_TEST_MARKER}")" == "${TMP}/agent-state/steam-anonymous-install-home" ]]
[[ "$(cat "${DSM_STEAM_TEST_MARKER}.xdg")" == "${TMP}/agent-state/steam-anonymous-install-home/.local/share" ]]
[[ "$(stat -c '%a' "${TMP}/agent-state/steam-anonymous-install-home")" == "700" ]]
[[ "$HOME" == "${TMP}/authenticated-home" ]]
# Refuse symlink-redirection without ever launching SteamCMD.
rm -rf -- "${TMP}/agent-state/steam-anonymous-install-home"
ln -s -- "${TMP}/authenticated-home" "${TMP}/agent-state/steam-anonymous-install-home"
rm -f -- "${DSM_STEAM_TEST_MARKER}" "${DSM_STEAM_TEST_MARKER}.xdg"
if steam_provider_install_anonymous 223350 "${TMP}/anonymous-install" >/dev/null 2>&1; then
    echo 'Unsafe SteamCMD anonymous-install HOME was accepted' >&2
    exit 1
fi
[[ ! -e "${DSM_STEAM_TEST_MARKER}" ]]
printf 'PASS: SteamCMD install output is not leaked and exit status is retained\n'
