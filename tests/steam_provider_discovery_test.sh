#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export DSM_ROOT="$TMP"
export CAPIVARA_AGENT_STATE_DIR="$TMP/agent"
mkdir -p "$TMP/tools/steamcmd/linux32" "$TMP/agent/.local/share/Steam/steamcmd" "$TMP/agent/tools/steamcmd"
for binary in "$TMP/tools/steamcmd/steamcmd.sh" "$TMP/tools/steamcmd/linux32/steamcmd" "$TMP/agent/.local/share/Steam/steamcmd/steamcmd.sh" "$TMP/agent/tools/steamcmd/steamcmd.sh"; do
    printf '#!/bin/sh\nexit 0\n' > "$binary"
    chmod +x "$binary"
done
source "$ROOT/installer/providers/steam.sh"
steam_provider_validate
[[ "$STEAMCMD_BIN" == "$TMP/tools/steamcmd/steamcmd.sh" ]] || exit 1
rm -rf "$TMP/tools/steamcmd"
STEAMCMD_ROOT="$TMP/tools/steamcmd"
STEAMCMD_BIN="$STEAMCMD_ROOT/steamcmd.sh"
steam_provider_validate
[[ "$STEAMCMD_BIN" == "$TMP/agent/.local/share/Steam/steamcmd/steamcmd.sh" ]] || exit 1
rm -f "$STEAMCMD_BIN"
STEAMCMD_ROOT="$TMP/tools/steamcmd"
STEAMCMD_BIN="$STEAMCMD_ROOT/steamcmd.sh"
steam_provider_validate
[[ "$STEAMCMD_BIN" == "$TMP/agent/tools/steamcmd/steamcmd.sh" ]] || exit 1
rm -f "$STEAMCMD_BIN"
STEAMCMD_ROOT="$TMP/tools/steamcmd"
STEAMCMD_BIN="$STEAMCMD_ROOT/steamcmd.sh"
if [[ -x /usr/games/steamcmd ]]; then
    steam_provider_validate
    [[ "$STEAMCMD_BIN" == /usr/games/steamcmd ]] || exit 1
    printf 'PASS: system SteamCMD fallback\n'
fi
printf 'PASS: managed and hybrid SteamCMD discovery\n'
