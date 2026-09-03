#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

mkdir -p "${TMP}/installed/.dsm" "${TMP}/versions"
cat >"${TMP}/installed/.dsm/local-provider.conf" <<'EOF'
PROVIDER=local
SOURCE=/tmp/source
TYPE=directory
FILENAME=''
SHA256=''
VERSION=100
EOF

cat >"${TMP}/versions/local.sh" <<'EOF'
provider_remote_version(){ printf '%s\n' "${MOCK_REMOTE:-100}"; }
export -f provider_remote_version
EOF

export DSM_ROOT="${ROOT}"
export DSM_PROVIDER_VERSION_ADAPTER_ROOT="${TMP}/versions"

OUT="$(MOCK_REMOTE=100 bash "${ROOT}/installer/update_monitor.sh" probe runtime local package "${TMP}/installed")"
jq -e '.kind=="UpdateProbe" and .target_kind=="runtime" and .status=="current" and .update_available==false and .installed_version=="100" and .remote_version=="100"' <<<"${OUT}" >/dev/null

OUT="$(MOCK_REMOTE=101 bash "${ROOT}/installer/update_monitor.sh" probe content local package "${TMP}/installed")"
jq -e '.target_kind=="content" and .status=="update_available" and .update_available==true and .installed_version=="100" and .remote_version=="101"' <<<"${OUT}" >/dev/null

# The generic monitor must remain game-neutral.
if grep -Eqi 'dayz|zomboid|arma|counter.?strike|rust|palworld' "${ROOT}/installer/update_monitor.sh"; then
    echo "update_monitor.sh contains game-specific logic" >&2
    exit 1
fi

# Steam and Workshop probes are provider-scoped adapters, not game adapters.
grep -q 'provider_remote_version' "${ROOT}/installer/provider_versions/steam.sh"
grep -q 'provider_remote_version' "${ROOT}/installer/provider_versions/steam-workshop.sh"
grep -q 'GetPublishedFileDetails' "${ROOT}/installer/provider_versions/steam-workshop.sh"
grep -q 'app_info_print' "${ROOT}/installer/provider_versions/steam.sh"

echo "generic update monitor: OK"
