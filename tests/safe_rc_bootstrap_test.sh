#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BOOTSTRAP="$ROOT/release/safe_rc_bootstrap.sh"
T=$(mktemp -d /tmp/dsm-rc132-bootstrap-test.XXXXXXXX)
trap 'rm -rf -- "$T"' EXIT
mkdir -p "$T/installed" "$T/package/capivara-dsm-2.0.132/update-manager"
printf '2.0.132-rc.4\n' >"$T/installed/version"
printf '2.0.132\n' >"$T/package/capivara-dsm-2.0.132/version"
cat >"$T/package/capivara-dsm-2.0.132/update-manager/preflight.sh" <<'PRE'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$(cat "$1/version")" == "2.0.132" ]]
[[ "$(cat "$2/version")" == "2.0.132-rc.4" ]]
echo MOCK_PREFLIGHT_READ_ONLY_OK
PRE
cat >"$T/package/capivara-dsm-2.0.132/update.sh" <<'UPDATE'
#!/usr/bin/env bash
echo "SHOULD NEVER EXECUTE" >&2
exit 99
UPDATE
PKG="$T/capivara-dsm-2.0.132.tar.gz"
tar -czf "$PKG" -C "$T/package" capivara-dsm-2.0.132
sha256sum "$PKG" >"$PKG.sha256"
bash "$BOOTSTRAP" --preflight "$PKG" "$PKG.sha256" --installed-root "$T/installed" |
  grep -q SAFE_RC_BOOTSTRAP_PREFLIGHT=PASS
echo SAFE_BOOTSTRAP_GOOD_CHECKSUM=PASS
printf '%064d  %s\n' 0 "$PKG" > "$T/bad.sha256"
if bash "$BOOTSTRAP" --preflight "$PKG" "$T/bad.sha256" --installed-root "$T/installed" >/dev/null 2>&1; then
  echo 'unsafe checksum accepted' >&2; exit 1
fi
echo SAFE_BOOTSTRAP_BAD_CHECKSUM=REJECTED
if bash "$BOOTSTRAP" --apply "$PKG" "$PKG.sha256" --installed-root "$T/installed" >/dev/null 2>&1; then
  echo 'unsafe target accepted for apply' >&2; exit 1
fi
echo SAFE_BOOTSTRAP_NONPRODUCTION_APPLY=REJECTED
printf '2.0.132\n' > "$T/installed/version"
if bash "$BOOTSTRAP" --preflight "$PKG" "$PKG.sha256" --installed-root "$T/installed" >/dev/null 2>&1; then
  echo 'wrong installed version accepted' >&2; exit 1
fi
echo SAFE_BOOTSTRAP_VERSION_GUARD=PASS
printf '2.0.132-rc.4\n' > "$T/installed/version"
python3 - "$T" <<'PY'
import io,tarfile,sys
from pathlib import Path
base=Path(sys.argv[1])
p=base/"capivara-dsm-2.0.132.tar.gz"
with tarfile.open(p,"w:gz") as t:
  data=b'not allowed'
  info=tarfile.TarInfo("capivara-dsm-2.0.132/../../outside")
  info.size=len(data)
  t.addfile(info,io.BytesIO(data))
PY
sha256sum "$PKG" >"$PKG.sha256"
if bash "$BOOTSTRAP" --preflight "$PKG" "$PKG.sha256" --installed-root "$T/installed" >/dev/null 2>&1; then
  echo 'unsafe archive accepted' >&2; exit 1
fi
echo SAFE_BOOTSTRAP_ARCHIVE_TRAVERSAL=REJECTED
echo SAFE_BOOTSTRAP_ALL_TESTS=PASS
