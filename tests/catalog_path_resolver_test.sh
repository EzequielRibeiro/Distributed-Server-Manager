#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DSM_ROOT="${ROOT}"

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

SOURCE_RUNTIME="${ROOT}/catalog/v2/runtimes/dayz/stable.json"

# 1. Legacy-only lookup must remain compatible.
LEGACY_ROOT="${TMP_DIR}/legacy"
mkdir -p "${LEGACY_ROOT}/runtimes/dayz"
cp "${SOURCE_RUNTIME}" "${LEGACY_ROOT}/runtimes/dayz/stable.json"
LEGACY_SHOW="$(DSM_CATALOG_ROOT="${LEGACY_ROOT}" "${ROOT}/installer/catalog.sh" runtime show dayz.stable --json)"
jq -e '.id == "dayz.stable" and .game == "dayz"' <<<"${LEGACY_SHOW}" >/dev/null \
    || fail "legacy-only runtime lookup failed"

# 2. Canonical-only lookup must work before any physical migration.
CANONICAL_ROOT="${TMP_DIR}/canonical"
mkdir -p "${CANONICAL_ROOT}/games/dayz/runtimes"
cp "${SOURCE_RUNTIME}" "${CANONICAL_ROOT}/games/dayz/runtimes/stable.json"
CANONICAL_SHOW="$(DSM_CATALOG_ROOT="${CANONICAL_ROOT}" "${ROOT}/installer/catalog.sh" runtime show dayz.stable --json)"
jq -e '.id == "dayz.stable" and .game == "dayz"' <<<"${CANONICAL_SHOW}" >/dev/null \
    || fail "canonical-only runtime lookup failed"

# 3. When both layouts contain the same ID, canonical must win.
MIXED_ROOT="${TMP_DIR}/mixed"
mkdir -p "${MIXED_ROOT}/runtimes/dayz" "${MIXED_ROOT}/games/dayz/runtimes"
cp "${SOURCE_RUNTIME}" "${MIXED_ROOT}/runtimes/dayz/stable.json"
jq '.name = "Canonical DayZ Marker"' "${SOURCE_RUNTIME}" \
    >"${MIXED_ROOT}/games/dayz/runtimes/stable.json"
MIXED_SHOW="$(DSM_CATALOG_ROOT="${MIXED_ROOT}" "${ROOT}/installer/catalog.sh" runtime show dayz.stable --json)"
jq -e '.name == "Canonical DayZ Marker"' <<<"${MIXED_SHOW}" >/dev/null \
    || fail "canonical runtime did not override legacy duplicate"

# 4. Listing must de-duplicate IDs across canonical and legacy layouts.
MIXED_LIST="$(DSM_CATALOG_ROOT="${MIXED_ROOT}" "${ROOT}/installer/catalog.sh" runtime list dayz --json)"
[[ "$(jq '[.[] | select(.id == "dayz.stable")] | length' <<<"${MIXED_LIST}")" -eq 1 ]] \
    || fail "runtime list exposed duplicate ID across layouts"
jq -e '.[] | select(.id == "dayz.stable") | .name == "Canonical DayZ Marker"' <<<"${MIXED_LIST}" >/dev/null \
    || fail "runtime list did not preserve canonical definition"

# Runtime preparation must use the same path resolver as show/list.
MIXED_SELECTION="$(DSM_CATALOG_ROOT="${MIXED_ROOT}" "${ROOT}/installer/catalog.sh" runtime prepare dayz.stable current --json)"
jq -e '.runtime_definition == "dayz.stable" and .provider == "steam" and .install.package_id == "223350"' \
    <<<"${MIXED_SELECTION}" >/dev/null || fail "runtime prepare bypassed path resolver"

echo "Catalog path resolver compatibility tests passed."
