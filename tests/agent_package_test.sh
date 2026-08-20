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

bash "${BUILDER}" HEAD "${TMP}/one" >/dev/null
bash "${BUILDER}" HEAD "${TMP}/two" >/dev/null
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
for path in install-agent.sh manifest.json VERSION agent/common/identity.py agent/runtime/agent.py agent/runtime/capabilities.py agent/runtime/network_inventory.py services/capivara-agent.service config/README.md; do
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
for relative in (
    'agent/common/identity.py',
    'agent/runtime/agent.py',
    'agent/runtime/capabilities.py',
    'agent/runtime/network_inventory.py',
    'services/capivara-agent.service',
):
    source = root / ('agents/linux/' + relative.removeprefix('agent/') if relative.startswith('agent/runtime/') else 'agents/' + relative if relative.startswith('agent/common/') else 'agents/linux/services/capivara-agent.service')
    if relative == 'agent/common/identity.py':
        source = root / 'agents/common/identity.py'
    elif relative.startswith('agent/runtime/'):
        source = root / 'agents/linux/runtime' / pathlib.Path(relative).name
    assert (package / relative).read_bytes() == source.read_bytes()
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
