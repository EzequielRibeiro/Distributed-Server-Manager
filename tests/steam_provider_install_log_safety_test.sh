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
printf 'PASS: SteamCMD install output is not leaked and exit status is retained\n'
