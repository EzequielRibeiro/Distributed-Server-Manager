#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE="${ROOT}/update-manager/update-manager.sh"

fail(){ echo "FAIL: $*" >&2; exit 1; }

TMP_ROOT="$(mktemp -d)"
# The pre-existing legacy path is never touched by the new updater.
LEGACY_DIR="/tmp/dsm-update"
TMPDIR="${TMP_ROOT}"
export TMPDIR
cleanup()
{
    rm -rf -- "${TMP_ROOT}"
}
trap cleanup EXIT

DSM_ROOT="${TMP_ROOT}/installed"
PACKAGE_SRC="${TMP_ROOT}/release/capivara-dsm-1.4.6"
PACKAGE_TAR="${TMP_ROOT}/capivara-dsm-1.4.6.tar.gz"
CHECKSUM_FILE="${TMP_ROOT}/capivara-dsm-1.4.6.tar.gz.sha256"
MARKER="${TMP_ROOT}/updater-marker"

mkdir -p \
    "${DSM_ROOT}/core" \
    "${DSM_ROOT}/update-manager" \
    "${PACKAGE_SRC}"

printf '1.4.5\n' >"${DSM_ROOT}/version"

cat >"${DSM_ROOT}/core/bootstrap.sh" <<'EOF'
log_info(){ :; }
log_error(){ printf '%s\n' "$*" >&2; }
is_semver(){ [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; }
semver_compare()
{
    if [[ "$1" == "$2" ]]; then printf '0\n'; return; fi
    if [[ "$1" == "1.4.6" && "$2" == "1.4.5" ]]; then printf '1\n'; return; fi
    printf '%s\n' '-1'
}
events_emit(){ :; }
EOF

cat >"${DSM_ROOT}/update-manager/config.conf" <<EOF
INSTALL_DIR="${DSM_ROOT}"
HISTORY_FILE="${TMP_ROOT}/history.log"
EOF

: >"${DSM_ROOT}/update-manager/github-client.sh"
: >"${DSM_ROOT}/update-manager/download-release.sh"
: >"${DSM_ROOT}/update-manager/verify-release.sh"

cat >"${DSM_ROOT}/update.sh" <<EOF
#!/usr/bin/env bash
printf 'old\n' >"${MARKER}"
EOF
chmod +x "${DSM_ROOT}/update.sh"

printf '1.4.6\n' >"${PACKAGE_SRC}/version"
cat >"${PACKAGE_SRC}/update.sh" <<EOF
#!/usr/bin/env bash
[[ "\$1" == ${TMP_ROOT}/dsm-update.*/capivara-dsm-1.4.6 ]] || exit 41
printf 'target\n' >"${MARKER}"
printf '1.4.6\n' >"${DSM_ROOT}/version"
EOF
chmod +x "${PACKAGE_SRC}/update.sh"

tar -czf "${PACKAGE_TAR}" -C "${TMP_ROOT}/release" capivara-dsm-1.4.6
printf '%064d  %s\n' 0 "${PACKAGE_TAR}" >"${CHECKSUM_FILE}"

export DSM_ROOT
# shellcheck source=/dev/null
source "${MODULE}"

github_latest_release(){ printf '%s\n' 'release-json'; }
github_release_version(){ printf '%s\n' 'v1.4.6'; }
github_release_download(){ printf '%s\n' 'release-url'; }
github_release_checksum_download(){ printf '%s\n' 'checksum-url'; }
download_release(){ printf '%s\n' "${PACKAGE_TAR}"; }
download_checksum(){ printf '%s\n' "${CHECKSUM_FILE}"; }
verify_release(){ return 0; }
dsm_update_notify(){ :; }
events_emit(){ :; }

legacy_snapshot=""
if [[ -d "${LEGACY_DIR}" ]]; then
    legacy_snapshot="$(stat -c '%d:%i:%Y' "${LEGACY_DIR}")"
fi

dsm_update_run >/dev/null

# Every temporary workspace is automatically deleted. The preexisting fixed
# path is untouched even when it belongs to another or older transaction.
[[ -z "$(find "${TMP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'dsm-update.*' -print -quit)" ]] \
    || fail "unique update handoff left behind"
if [[ -n "${legacy_snapshot}" ]]; then
    [[ "$(stat -c '%d:%i:%Y' "${LEGACY_DIR}")" == "${legacy_snapshot}" ]] \
        || fail "legacy /tmp/dsm-update was modified"
fi

[[ -f "${MARKER}" ]] || fail "no updater was executed"
[[ "$(cat "${MARKER}")" == "target" ]] \
    || fail "installed updater executed instead of target release updater"
[[ "$(cat "${DSM_ROOT}/version")" == "1.4.6" ]] \
    || fail "target updater did not install the expected version"

printf 'Target updater handoff regression passed.\n'
