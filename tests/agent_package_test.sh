#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILDER="${ROOT}/release/build_agent_package.sh"
TMP=$(mktemp -d)
cleanup(){ rm -rf -- "${TMP}"; }
trap cleanup EXIT
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

bash -n "${BUILDER}"
bash -n "${ROOT}/agents/linux/installer/bootstrap-release.sh"
bash -n "${ROOT}/agents/linux/installer/install-agent.sh"

"${BUILDER}" HEAD "${TMP}/one" >/dev/null
"${BUILDER}" HEAD "${TMP}/two" >/dev/null
VERSION=$(tr -d '\r\n' <"${ROOT}/version")
ARCHIVE="capivara-agent-linux-${VERSION}.tar.gz"

cmp -s "${TMP}/one/${ARCHIVE}" "${TMP}/two/${ARCHIVE}" || fail "Agent package is not reproducible"
(
  cd "${TMP}/one"
  sha256sum -c "${ARCHIVE}.sha256" >/dev/null
)

mkdir "${TMP}/extract"
tar -xzf "${TMP}/one/${ARCHIVE}" -C "${TMP}/extract"
PACKAGE="${TMP}/extract/capivara-agent-linux-${VERSION}"
for path in install-agent.sh manifest.json VERSION agent/common/identity.py agent/runtime/agent.py services/capivara-agent.service config/README.md; do
  [[ -f "${PACKAGE}/${path}" ]] || fail "missing Agent package file: ${path}"
done

python3 - "${PACKAGE}" "${ROOT}" <<'PY'
import hashlib, json, pathlib, sys
package, root = map(pathlib.Path, sys.argv[1:])
manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
assert manifest['kind'] == 'CapivaraAgentPackage'
assert manifest['platform'] == 'linux'
assert manifest['version'] == (package / 'VERSION').read_text().strip()
for relative in manifest['required_files']:
    data = (package / relative).read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest['files'][relative]['sha256']
# Release package and local/offline package are made from the same tracked sources.
assert (package/'agent/common/identity.py').read_bytes() == (root/'agents/common/identity.py').read_bytes()
assert (package/'agent/runtime/agent.py').read_bytes() == (root/'agents/linux/runtime/agent.py').read_bytes()
assert (package/'services/capivara-agent.service').read_bytes() == (root/'agents/linux/services/capivara-agent.service').read_bytes()
PY

INSTALLER="${PACKAGE}/install-agent.sh"
BOOTSTRAP="${ROOT}/agents/linux/installer/bootstrap-release.sh"
grep -Fq -- '--package-dir' "${INSTALLER}" || fail "local installer lacks --package-dir"
! grep -Fq 'api.github.com' "${INSTALLER}" || fail "local installer depends on GitHub"
! grep -Fq 'git clone' "${INSTALLER}" || fail "local installer clones source"
grep -Fq 'capivara-agent-linux-' "${BOOTSTRAP}" || fail "release bootstrap does not select Agent package"
grep -Fq 'sha256sum' "${BOOTSTRAP}" || fail "release bootstrap does not validate checksum"
! grep -Fq '/main/' "${BOOTSTRAP}" || fail "release bootstrap follows mutable main"

echo "Agent package tests passed."
