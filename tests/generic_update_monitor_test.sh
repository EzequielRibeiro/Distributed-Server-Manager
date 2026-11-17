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

touch "${TMP}/request.json"
mkdir -p "${TMP}/instance"
set +e
bash "${ROOT}/installer/update_monitor.sh" apply-content "${TMP}/request.json" "${TMP}/instance" >/dev/null 2>"${TMP}/apply-content.err"
APPLY_CONTENT_STATUS=$?
set -e
[[ "${APPLY_CONTENT_STATUS}" -eq 3 ]] || { echo "legacy apply-content was not retired" >&2; exit 1; }
grep -Fq 'Universal Content Platform' "${TMP}/apply-content.err" || { echo "retired apply-content lacks UCP migration guidance" >&2; exit 1; }

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

# Legacy Steam version adapter must use isolated SteamCMD HOME as well.
mkdir -p "${TMP}/agent-state" "${TMP}/fakebin"
cat >"${TMP}/fakebin/steamcmd" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${HOME}" > "${DSM_STEAM_PROBE_HOME_MARKER}"
printf '%s\n' '"branches"' '{' '"public"' '{' '"buildid" "123456"' '}' '}'
EOF
chmod 700 "${TMP}/fakebin/steamcmd"
# Source only the adapter; never run installation or real SteamCMD.
OUT="$(
  export STEAMCMD_BIN="${TMP}/fakebin/steamcmd"
  export CAPIVARA_AGENT_STATE_DIR="${TMP}/agent-state"
  export DSM_STEAM_PROBE_HOME_MARKER="${TMP}/steam-home-marker"
  export HOME="${TMP}/authenticated-home"
  mkdir -p "${HOME}"
  source "${ROOT}/installer/provider_versions/steam.sh"
  provider_remote_version 223350
)"
[[ "${OUT}" == "123456" ]]
[[ "$(cat "${TMP}/steam-home-marker")" == "${TMP}/agent-state/steam-anonymous-metadata-home" ]]
[[ "$(stat -c '%a' "${TMP}/agent-state/steam-anonymous-metadata-home")" == "700" ]]
# A symbolic-link destination must fail closed without invoking SteamCMD.
rm -rf "${TMP}/agent-state/steam-anonymous-metadata-home"
ln -s "${TMP}/authenticated-home" "${TMP}/agent-state/steam-anonymous-metadata-home"
if (
  export STEAMCMD_BIN="${TMP}/fakebin/steamcmd"
  export CAPIVARA_AGENT_STATE_DIR="${TMP}/agent-state"
  source "${ROOT}/installer/provider_versions/steam.sh"
  provider_remote_version 223350
) >/dev/null 2>&1; then
  echo "legacy Steam adapter followed an unsafe session symlink" >&2
  exit 1
fi

echo "generic update monitor: OK"
