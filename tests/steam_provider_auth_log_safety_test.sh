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
printf '%s\n' 'Steam Guard secret=DO_NOT_LEAK_TO_JOB_LOG'
exit 1
MOCK
chmod +x "$STEAMCMD_BIN"
OUTPUT="$(steam_provider_install_authenticated 223350 "$TMP/install" steam-test-user 2>&1)" && {
    echo 'Expected authentication failure' >&2
    exit 1
}
[[ "$OUTPUT" == *'Autenticação Steam necessária ou expirada.'* ]]
[[ "$OUTPUT" != *'DO_NOT_LEAK_TO_JOB_LOG'* ]]
[[ "$OUTPUT" != *'Steam Guard secret'* ]]
# SteamCMD can return success despite a failed or unauthenticated login.
# The installer must refuse to run +app_update in those cases.
cat > "$STEAMCMD_BIN" <<'MOCK'
#!/bin/sh
case "$*" in
  *+app_update*) touch "$DSM_STEAM_MOCK_APP_UPDATE_MARKER"; exit 0 ;;
esac
printf '%s\n' 'Loading Steam API...OK' 'Waiting for user info...OK' 'Sensitive=PRIVATE_ACCOUNT_TOKEN'
exit 0
MOCK
chmod +x "$STEAMCMD_BIN"
export DSM_STEAM_MOCK_APP_UPDATE_MARKER="$TMP/forbidden-app-update"
set +e
OUTPUT="$(steam_provider_install_authenticated 223350 "$TMP/install" steam-test-user 2>&1)"
STATUS=$?
set -e
[[ "$STATUS" -eq 42 ]]
[[ ! -e "$DSM_STEAM_MOCK_APP_UPDATE_MARKER" ]]
[[ "$OUTPUT" != *PRIVATE_ACCOUNT_TOKEN* ]]

# Failure messages override a forged/partial success marker even with exit 0.
cat > "$STEAMCMD_BIN" <<'MOCK'
#!/bin/sh
case "$*" in
  *+app_update*) touch "$DSM_STEAM_MOCK_APP_UPDATE_MARKER"; exit 0 ;;
esac
printf '%s\n' "Logging in user 'steam-test-user' to Steam Public...OK" 'ERROR! Login Failure: session expired'
exit 0
MOCK
chmod +x "$STEAMCMD_BIN"
set +e
OUTPUT="$(steam_provider_install_authenticated 223350 "$TMP/install" steam-test-user 2>&1)"
STATUS=$?
set -e
[[ "$STATUS" -eq 42 ]]
[[ ! -e "$DSM_STEAM_MOCK_APP_UPDATE_MARKER" ]]
[[ "$OUTPUT" != *'session expired'* ]]

# A successful login for the wrong Steam account must not authorize installs.
cat > "$STEAMCMD_BIN" <<'MOCK'
#!/bin/sh
case "$*" in
  *+app_update*) touch "$DSM_STEAM_MOCK_APP_UPDATE_MARKER"; exit 0 ;;
esac
printf '%s\n' "Logging in user 'anonymous' to Steam Public...OK" 'Logged in OK'
exit 0
MOCK
chmod +x "$STEAMCMD_BIN"
set +e
OUTPUT="$(steam_provider_install_authenticated 223350 "$TMP/install" steam-test-user 2>&1)"
STATUS=$?
set -e
[[ "$STATUS" -eq 42 ]]
[[ ! -e "$DSM_STEAM_MOCK_APP_UPDATE_MARKER" ]]

# A real account login marker permits the follow-on installer command.
cat > "$STEAMCMD_BIN" <<'MOCK'
#!/bin/sh
case "$*" in
  *+app_update*) touch "$DSM_STEAM_MOCK_APP_UPDATE_MARKER"; exit 0 ;;
esac
printf '%s\n' "Logging in user 'steam-test-user' to Steam Public...OK"
exit 0
MOCK
chmod +x "$STEAMCMD_BIN"
steam_provider_install_authenticated 223350 "$TMP/install" steam-test-user >/dev/null
[[ -e "$DSM_STEAM_MOCK_APP_UPDATE_MARKER" ]]
printf 'PASS: Steam authentication failure does not expose raw SteamCMD output\n'
