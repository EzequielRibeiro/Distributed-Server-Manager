#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DSM_ROOT="${ROOT}"

fail(){ echo "FAIL: $*" >&2; exit 1; }

ACTIVE="$("${ROOT}/installer/catalog.sh" runtime list --json)"
EXPECTED_ACTIVE="$(find "${ROOT}/catalog/v2/games" -path '*/runtimes/*.json' -type f | wc -l)"
[[ "$(jq 'length' <<<"${ACTIVE}")" -eq "${EXPECTED_ACTIVE}" ]] || fail "active runtime list does not match published RuntimeDefinitions"

MINECRAFT_ACTIVE="$("${ROOT}/installer/catalog.sh" runtime list minecraft --json)"
[[ "$(jq 'length' <<<"${MINECRAFT_ACTIVE}")" -eq 0 ]] || fail "deferred Minecraft runtimes must not be published as executable"

while IFS= read -r deferred; do
  runtime_id="$(jq -r '.id' "${deferred}")"
  jq -e --arg id "${runtime_id}" 'map(.id) | index($id) == null' <<<"${ACTIVE}" >/dev/null \
    || fail "deferred runtime published as active: ${runtime_id}"
done < <(find "${ROOT}/catalog/v2/games" -path '*/deferred/*.json' -type f | sort)

bash "${ROOT}/tests/catalog_v2_all_definitions_test.sh"
