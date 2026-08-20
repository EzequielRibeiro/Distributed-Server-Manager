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
for path in \
  install-agent.sh manifest.json VERSION \
  agent/common/identity.py \
  agent/runtime/agent.py agent/runtime/capabilities.py agent/runtime/network_inventory.py agent/runtime/update_client.py \
  agent/updater/updater.py \
  services/capivara-agent.service services/capivara-agent-update.service services/capivara-agent-update.path \
  config/README.md
do
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
source_map = {
    'agent/common/identity.py': root / 'agents/common/identity.py',
    'agent/runtime/agent.py': root / 'agents/linux/runtime/agent.py',
    'agent/runtime/capabilities.py': root / 'agents/linux/runtime/capabilities.py',
    'agent/runtime/network_inventory.py': root / 'agents/linux/runtime/network_inventory.py',
    'agent/runtime/update_client.py': root / 'agents/linux/runtime/update_client.py',
    'agent/updater/updater.py': root / 'agents/linux/updater/updater.py',
    'services/capivara-agent.service': root / 'agents/linux/services/capivara-agent.service',
    'services/capivara-agent-update.service': root / 'agents/linux/services/capivara-agent-update.service',
    'services/capivara-agent-update.path': root / 'agents/linux/services/capivara-agent-update.path',
}
for relative, source in source_map.items():
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
grep -Fq 'capivara-agent-update.path' "${INSTALLER}" || fail "installer does not enable safe remote updater"

echo "Agent package tests passed."
