#!/usr/bin/env bash
# One-time safe entry for DSM 2.0.132-rc.4 -> 2.0.132.
# Avoid invoking the old installed update-manager or touching /tmp/dsm-update.
set -Eeuo pipefail

usage() {
  printf 'Usage: %s --preflight|--apply PACKAGE.tar.gz PACKAGE.tar.gz.sha256 [--installed-root DIR]\n' "$0"
}
[[ $# -ge 3 ]] || { usage >&2; exit 2; }
mode="$1"; package="$2"; checksum_file="$3"; shift 3
installed_root="/opt/dsm"
if [[ $# -eq 2 && "$1" == "--installed-root" ]]; then
  installed_root="$2"
elif [[ $# -ne 0 ]]; then
  usage >&2; exit 2
fi
[[ "$mode" == "--preflight" || "$mode" == "--apply" ]] || { usage >&2; exit 2; }
[[ -f "$package" && ! -L "$package" && -f "$checksum_file" && ! -L "$checksum_file" ]] || {
  echo 'BOOTSTRAP BLOCK: package/checksum missing or symbolic link' >&2; exit 1;
}
[[ -r "$installed_root/version" ]] || { echo 'BOOTSTRAP BLOCK: installed version missing' >&2; exit 1; }
[[ "$(tr -d '\r\n' <"$installed_root/version")" == "2.0.132-rc.4" ]] || {
  echo 'BOOTSTRAP BLOCK: expected installed DSM 2.0.132-rc.4' >&2; exit 1;
}
[[ "$(basename "$package")" == "capivara-dsm-2.0.132.tar.gz" ]] || {
  echo 'BOOTSTRAP BLOCK: unexpected package name' >&2; exit 1;
}
expected="$(awk 'NR==1 {print $1}' "$checksum_file")"
[[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || { echo 'BOOTSTRAP BLOCK: invalid SHA256 file' >&2; exit 1; }
actual="$(sha256sum -- "$package" | awk '{print $1}')"
[[ "${actual,,}" == "${expected,,}" ]] || { echo 'BOOTSTRAP BLOCK: SHA256 mismatch' >&2; exit 1; }
# Reject archive members outside the one expected release root and reject
# links/devices; tar must never traverse outside a private extraction root.
python3 - "$package" <<'VERIFY_ARCHIVE'
from pathlib import PurePosixPath
import sys
import tarfile
prefix = "capivara-dsm-2.0.132"
with tarfile.open(sys.argv[1], "r:gz") as archive:
    members = archive.getmembers()
    if not members:
        raise SystemExit("BOOTSTRAP BLOCK: empty archive")
    for entry in members:
        path = PurePosixPath(entry.name)
        if (path.is_absolute() or ".." in path.parts
                or not path.parts or path.parts[0] != prefix
                or not (entry.isfile() or entry.isdir())):
            raise SystemExit("BOOTSTRAP BLOCK: unsafe archive member")
VERIFY_ARCHIVE
workspace="$(mktemp -d "${TMPDIR:-/tmp}/dsm-rc132-bootstrap.XXXXXXXX")"
chmod 0700 "$workspace"
cleanup() { rm -rf -- "$workspace"; }
trap cleanup EXIT
# Extract into a private workspace, never the legacy /tmp/dsm-update path.
tar --extract --gzip --file "$package" --directory "$workspace" \
  --no-same-owner --no-same-permissions
root="$workspace/capivara-dsm-2.0.132"
[[ -d "$root" && ! -L "$root" && -f "$root/version" && -f "$root/update.sh" && -f "$root/update-manager/preflight.sh" ]] || {
  echo 'BOOTSTRAP BLOCK: invalid release structure' >&2; exit 1;
}
[[ "$(tr -d '\r\n' <"$root/version")" == "2.0.132" ]] || {
  echo 'BOOTSTRAP BLOCK: package version mismatch' >&2; exit 1;
}
# The package's own read-only preflight must succeed before opening a window.
bash "$root/update-manager/preflight.sh" "$root" "$installed_root"
echo 'SAFE_RC_BOOTSTRAP_PREFLIGHT=PASS'
if [[ "$mode" == "--preflight" ]]; then exit 0; fi
[[ "$installed_root" == "/opt/dsm" && "${EUID}" -eq 0 ]] || {
  echo 'BOOTSTRAP BLOCK: apply requires root and /opt/dsm' >&2; exit 1;
}
[[ "${DSM_RC132_APPLY_APPROVED:-}" == "2.0.132" ]] || {
  echo 'BOOTSTRAP BLOCK: explicit DSM_RC132_APPLY_APPROVED=2.0.132 required' >&2; exit 1;
}
# No old cap update run; target updater alone controls backup/staging/rollback.
bash "$root/update.sh" --yes "$root"
[[ "$(tr -d '\r\n' <"/opt/dsm/version")" == "2.0.132" ]] || {
  echo 'BOOTSTRAP BLOCK: target updater did not install expected version' >&2; exit 1;
}
echo 'SAFE_RC_BOOTSTRAP_APPLY=PASS'
