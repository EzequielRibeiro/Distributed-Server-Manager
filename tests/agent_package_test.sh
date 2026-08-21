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
python3 -m py_compile \
  "${ROOT}/agents/linux/runtime/agent.py" \
  "${ROOT}/agents/linux/runtime/local_cli.py" \
  "${ROOT}/agents/linux/runtime/cap_dispatch.py" \
  "${ROOT}/agents/linux/runtime/update_state.py" \
  "${ROOT}/agents/linux/runtime/game_data_client.py" \
  "${ROOT}/agents/linux/runtime/game_data_executor.py" \
  "${ROOT}/agents/linux/runtime/game_data_state.py" \
  "${ROOT}/agents/linux/runtime/instance_runtime.py" \
  "${ROOT}/agents/linux/runtime/instance_provisioning_client.py" \
  "${ROOT}/agents/linux/runtime/adapters/base.py" \
  "${ROOT}/agents/linux/runtime/adapters/registry.py" \
  "${ROOT}/agents/linux/runtime/adapters/systemd.py" \
  "${ROOT}/agents/linux/provisioner/instance_provisioner.py" \
  "${ROOT}/agents/linux/updater/updater.py"

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
  agent/runtime/agent.py agent/runtime/capabilities.py agent/runtime/network_inventory.py \
  agent/runtime/update_client.py agent/runtime/update_state.py agent/runtime/local_cli.py agent/runtime/cap_dispatch.py \
  agent/runtime/game_data_client.py agent/runtime/game_data_executor.py agent/runtime/game_data_state.py \
  agent/runtime/instance_runtime.py agent/runtime/instance_provisioning_client.py \
  agent/runtime/adapters/__init__.py agent/runtime/adapters/base.py agent/runtime/adapters/registry.py agent/runtime/adapters/systemd.py \
  agent/provisioner/instance_provisioner.py agent/policy/49-capivara-agent-instance-units.rules \
  agent/updater/updater.py \
  services/capivara-agent.service services/capivara-agent-update.service services/capivara-agent-update.path \
  services/capivara-agent-instance-provisioner.service services/capivara-agent-instance-provisioner.path \
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
    'agent/runtime/update_state.py': root / 'agents/linux/runtime/update_state.py',
    'agent/runtime/local_cli.py': root / 'agents/linux/runtime/local_cli.py',
    'agent/runtime/cap_dispatch.py': root / 'agents/linux/runtime/cap_dispatch.py',
    'agent/runtime/game_data_client.py': root / 'agents/linux/runtime/game_data_client.py',
    'agent/runtime/game_data_executor.py': root / 'agents/linux/runtime/game_data_executor.py',
    'agent/runtime/game_data_state.py': root / 'agents/linux/runtime/game_data_state.py',
    'agent/runtime/instance_runtime.py': root / 'agents/linux/runtime/instance_runtime.py',
    'agent/runtime/instance_provisioning_client.py': root / 'agents/linux/runtime/instance_provisioning_client.py',
    'agent/runtime/adapters/__init__.py': root / 'agents/linux/runtime/adapters/__init__.py',
    'agent/runtime/adapters/base.py': root / 'agents/linux/runtime/adapters/base.py',
    'agent/runtime/adapters/registry.py': root / 'agents/linux/runtime/adapters/registry.py',
    'agent/runtime/adapters/systemd.py': root / 'agents/linux/runtime/adapters/systemd.py',
    'agent/provisioner/instance_provisioner.py': root / 'agents/linux/provisioner/instance_provisioner.py',
    'agent/policy/49-capivara-agent-instance-units.rules': root / 'agents/linux/policy/49-capivara-agent-instance-units.rules',
    'agent/updater/updater.py': root / 'agents/linux/updater/updater.py',
    'services/capivara-agent.service': root / 'agents/linux/services/capivara-agent.service',
    'services/capivara-agent-update.service': root / 'agents/linux/services/capivara-agent-update.service',
    'services/capivara-agent-update.path': root / 'agents/linux/services/capivara-agent-update.path',
    'services/capivara-agent-instance-provisioner.service': root / 'agents/linux/services/capivara-agent-instance-provisioner.service',
    'services/capivara-agent-instance-provisioner.path': root / 'agents/linux/services/capivara-agent-instance-provisioner.path',
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
grep -Fq 'capivara-agent-instance-provisioner.path' "${INSTALLER}" || fail "installer does not enable privileged instance provisioner"
grep -Fq 'runtime/local_cli.py' "${INSTALLER}" || fail "installer does not install local Agent CLI"
grep -Fq 'runtime/instance_provisioning_client.py' "${INSTALLER}" || fail "installer does not install provisioning client"
grep -Fq 'provisioner/instance_provisioner.py' "${INSTALLER}" || fail "installer does not install privileged provisioner"
grep -Fq 'runtime/update_state.py' "${INSTALLER}" || fail "installer does not install update state module"
grep -Fq 'update-history' "${INSTALLER}" || fail "installer does not create update history"
grep -Fq 'runtime/game_data_client.py' "${INSTALLER}" || fail "installer does not install game-data client"
grep -Fq 'runtime/game_data_executor.py' "${INSTALLER}" || fail "installer does not install game-data executor"
grep -Fq 'runtime/game_data_state.py' "${INSTALLER}" || fail "installer does not install game-data state module"
grep -Fq '/usr/local/bin/cap' "${INSTALLER}" || fail "installer does not expose the cap command"

echo "Agent package tests passed."
