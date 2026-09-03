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

SOURCE_RUNTIME="${ROOT}/catalog/v2/games/dayz/runtimes/stable.json"

[[ -f "${SOURCE_RUNTIME}" ]] || fail "canonical DayZ runtime is missing"
[[ ! -e "${ROOT}/catalog/v2/runtimes" ]] || fail "legacy runtime tree still exists after full migration"

# Every catalog game keeps a canonical runtime namespace, even when no runtime
# is currently publishable (Luanti is intentionally deferred).
for GAME in arma3 dayz luanti mindustry minecraft rust
do
    [[ -d "${ROOT}/catalog/v2/games/${GAME}/runtimes" ]] \
        || fail "canonical runtime directory missing for ${GAME}"
done

# 1. Legacy-only lookup remains compatible for external/older catalog roots.
LEGACY_ROOT="${TMP_DIR}/legacy"
mkdir -p "${LEGACY_ROOT}/runtimes/dayz"
cp "${SOURCE_RUNTIME}" "${LEGACY_ROOT}/runtimes/dayz/stable.json"
LEGACY_SHOW="$(DSM_CATALOG_ROOT="${LEGACY_ROOT}" "${ROOT}/installer/catalog.sh" runtime show dayz.stable --json)"
jq -e '.id == "dayz.stable" and .game == "dayz"' <<<"${LEGACY_SHOW}" >/dev/null \
    || fail "legacy-only runtime lookup failed"

# 2. Canonical-only lookup.
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

# 5. Runtime preparation must use the same path resolver as show/list.
MIXED_SELECTION="$(DSM_CATALOG_ROOT="${MIXED_ROOT}" "${ROOT}/installer/catalog.sh" runtime prepare dayz.stable current --json)"
jq -e '.runtime_definition == "dayz.stable" and .provider == "steam" and .install.package_id == "223350"' \
    <<<"${MIXED_SELECTION}" >/dev/null || fail "runtime prepare bypassed path resolver"

# 6. Real repository catalog must expose every supported runtime exactly once.
ALL_RUNTIMES="$("${ROOT}/installer/catalog.sh" runtime list --json)"
for ID in \
    arma3.stable \
    dayz.stable \
    mindustry.github \
    minecraft.bedrock.vanilla \
    minecraft.java.arclight \
    minecraft.java.fabric \
    minecraft.java.forge \
    minecraft.java.neoforge \
    minecraft.java.paper \
    minecraft.java.vanilla \
    rust.stable
do
    [[ "$(jq --arg id "${ID}" '[.[] | select(.id == $id)] | length' <<<"${ALL_RUNTIMES}")" -eq 1 ]] \
        || fail "published runtime ${ID} is missing or duplicated"
done

[[ "$(jq '[.[] | select(.id == "luanti.stable")] | length' <<<"${ALL_RUNTIMES}")" -eq 0 ]] \
    || fail "deferred Luanti runtime is still published"

REPO_SHOW="$("${ROOT}/installer/catalog.sh" runtime show dayz.stable --json)"
jq -e '.id == "dayz.stable" and .artifact.package_id == "223350"' <<<"${REPO_SHOW}" >/dev/null \
    || fail "repository runtime show cannot resolve migrated DayZ definition"

echo "Catalog path resolver compatibility tests passed."
