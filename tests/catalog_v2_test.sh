#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DSM_ROOT="${ROOT}"

fail(){ echo "FAIL: $*" >&2; exit 1; }

ACTIVE="$("${ROOT}/installer/catalog.sh" runtime list --json)"
EXPECTED_ACTIVE="$(find "${ROOT}/catalog/v2/games" -path '*/runtimes/*.json' -type f | wc -l)"
[[ "$(jq 'length' <<<"${ACTIVE}")" -eq "${EXPECTED_ACTIVE}" ]] || fail "active runtime list does not match published RuntimeDefinitions"

MINECRAFT_ACTIVE="$("${ROOT}/installer/catalog.sh" runtime list minecraft --json)"
EXPECTED_MINECRAFT="$(find "${ROOT}/catalog/v2/games/minecraft/runtimes" -maxdepth 1 -name '*.json' -type f | wc -l)"
[[ "$(jq 'length' <<<"${MINECRAFT_ACTIVE}")" -eq "${EXPECTED_MINECRAFT}" ]] || fail "Minecraft runtime list does not match published RuntimeDefinitions"
jq -e 'all(.[]; (.game == "minecraft") and ((.edition == "java") or (.id == "minecraft.bedrock.vanilla" and .edition == "bedrock")))' <<<"${MINECRAFT_ACTIVE}" >/dev/null \
  || fail "published Minecraft runtimes must be supported Java runtimes or the canonical Bedrock runtime"
jq -e 'map(select(.id == "minecraft.bedrock.vanilla")) | length == 1' <<<"${MINECRAFT_ACTIVE}" >/dev/null \
  || fail "Minecraft Bedrock runtime must be published exactly once"

while IFS= read -r deferred; do
  runtime_id="$(jq -r '.id' "${deferred}")"
  jq -e --arg id "${runtime_id}" 'map(.id) | index($id) == null' <<<"${ACTIVE}" >/dev/null \
    || fail "deferred runtime published as active: ${runtime_id}"
done < <(find "${ROOT}/catalog/v2/games" -path '*/deferred/*.json' -type f | sort)

bash "${ROOT}/tests/catalog_v2_all_definitions_test.sh"
