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
printf 'PASS: Steam authentication failure does not expose raw SteamCMD output\n'
