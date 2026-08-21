#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILDER="${ROOT}/release/build_agent_package.sh"
TMP=$(mktemp -d)
cleanup(){ rm -rf -- "${TMP}"; }; trap cleanup EXIT
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

bash -n "${BUILDER}"
bash -n "${ROOT}/agents/linux/installer/bootstrap-release.sh"
bash -n "${ROOT}/agents/linux/installer/install-agent.sh"
python3 -m py_compile "${ROOT}"/agents/linux/runtime/*.py "${ROOT}"/agents/linux/runtime/adapters/*.py "${ROOT}"/agents/linux/runtime/materializers/*.py "${ROOT}"/agents/linux/runtime/profiles/*.py "${ROOT}/agents/linux/privileged/materialize_instance.py" "${ROOT}/agents/linux/updater/updater.py"

bash "${BUILDER}" HEAD "${TMP}/one" >/dev/null
bash "${BUILDER}" HEAD "${TMP}/two" >/dev/null
VERSION=$(tr -d '\r\n' <"${ROOT}/version"); ARCHIVE="capivara-agent-linux-${VERSION}.tar.gz"
cmp -s "${TMP}/one/${ARCHIVE}" "${TMP}/two/${ARCHIVE}" || fail "Agent package is not reproducible"
(cd "${TMP}/one" && sha256sum -c "${ARCHIVE}.sha256" >/dev/null)
mkdir "${TMP}/extract"; tar -xzf "${TMP}/one/${ARCHIVE}" -C "${TMP}/extract"; PACKAGE="${TMP}/extract/capivara-agent-linux-${VERSION}"
for path in install-agent.sh manifest.json VERSION agent/common/identity.py agent/privileged/materialize_instance.py agent/policy/49-capivara-agent-instance-units.rules agent/updater/updater.py services/capivara-agent.service services/capivara-agent-update.service services/capivara-agent-update.path services/capivara-agent-materialize@.service config/README.md; do [[ -f "${PACKAGE}/${path}" ]] || fail "missing Agent package file: ${path}"; done
for file in agent.py capabilities.py network_inventory.py update_client.py update_state.py local_cli.py cap_dispatch.py game_data_client.py game_data_executor.py game_data_state.py instance_runtime.py runtime_spec.py runtime_events.py runtime_materialization.py runtime_reconciler.py runtime_lock.py runtime_limits.py runtime_operations.py runtime_health.py runtime_metrics.py game_runtime.py provisioning_contract.py provisioning_state.py provisioning_client.py provisioning_executor.py privileged_materialization.py; do [[ -f "${PACKAGE}/agent/runtime/${file}" ]] || fail "missing Agent package runtime file: ${file}"; done

python3 - "${PACKAGE}" "${ROOT}" <<'PY'
import hashlib,json,pathlib,sys
package,root=map(pathlib.Path,sys.argv[1:]); manifest=json.loads((package/'manifest.json').read_text())
assert manifest['kind']=='CapivaraAgentPackage' and manifest['platform']=='linux'
assert manifest['version']==(package/'VERSION').read_text().strip()
for relative in manifest['required_files']:
 data=(package/relative).read_bytes(); assert hashlib.sha256(data).hexdigest()==manifest['files'][relative]['sha256']
for source in (root/'agents/linux/runtime').rglob('*.py'):
 rel='agent/runtime/'+source.relative_to(root/'agents/linux/runtime').as_posix(); assert (package/rel).read_bytes()==source.read_bytes(), rel
PY

INSTALLER="${PACKAGE}/install-agent.sh"; BOOTSTRAP="${ROOT}/agents/linux/installer/bootstrap-release.sh"
grep -Fq -- '--package-dir' "${INSTALLER}" || fail "local installer lacks --package-dir"
! grep -Fq 'api.github.com' "${INSTALLER}" || fail "local installer depends on GitHub"
! grep -Fq 'git clone' "${INSTALLER}" || fail "local installer clones source"
grep -Fq 'capivara-agent-linux-' "${BOOTSTRAP}" || fail "release bootstrap does not select Agent package"
grep -Fq 'sha256sum' "${BOOTSTRAP}" || fail "release bootstrap does not validate checksum"
! grep -Fq '/main/' "${BOOTSTRAP}" || fail "release bootstrap follows mutable main"
for file in runtime_reconciler.py runtime_lock.py runtime_limits.py runtime_operations.py runtime_health.py runtime_metrics.py; do grep -Fq "$file" "${INSTALLER}" || fail "installer does not install ${file}"; done
grep -Fq 'rglob("*.py")' "${ROOT}/agents/linux/updater/updater.py" || fail "updater does not dynamically manage runtime Python modules"
grep -Fq 'instance-locks' "${INSTALLER}" || fail "installer does not create instance lock state"
grep -Fq 'instance-operations' "${INSTALLER}" || fail "installer does not create operation journal state"
grep -Fq '/usr/local/bin/cap' "${INSTALLER}" || fail "installer does not expose cap command"

echo "Agent package tests passed."
