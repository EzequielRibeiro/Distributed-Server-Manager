#!/usr/bin/env bash
set -Eeuo pipefail

CONTROLLER_URL=""; PAIRING_TOKEN="${CAPIVARA_PAIRING_TOKEN:-}"; PACKAGE_DIR=""
INSTALL_ROOT="${CAPIVARA_AGENT_ROOT:-/opt/capivara-agent}"; CONFIG_DIR="${CAPIVARA_AGENT_CONFIG_DIR:-/etc/capivara-agent}"
STATE_DIR="${CAPIVARA_AGENT_STATE_DIR:-/var/lib/capivara-agent}"; SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
POLKIT_RULES_DIR="${CAPIVARA_POLKIT_RULES_DIR:-/etc/polkit-1/rules.d}"; CLI_PATH="${CAPIVARA_AGENT_CLI_PATH:-/usr/local/bin/cap}"
fail(){ printf '[Capivara Agent][ERRO] %s\n' "$*" >&2; exit 1; }; log(){ printf '[Capivara Agent] %s\n' "$*"; }
usage(){ printf '%s\n' 'Uso: sudo ./install-agent.sh --controller-url https://controller.exemplo --pairing-token TOKEN [--package-dir DIR]'; }
while (( $# )); do case "$1" in
  --controller-url) [[ $# -ge 2 ]] || fail "--controller-url requer valor"; CONTROLLER_URL="$2"; shift 2;;
  --pairing-token) [[ $# -ge 2 ]] || fail "--pairing-token requer valor"; PAIRING_TOKEN="$2"; shift 2;;
  --package-dir) [[ $# -ge 2 ]] || fail "--package-dir requer valor"; PACKAGE_DIR="$2"; shift 2;;
  --help|-h) usage; exit 0;; *) fail "opção desconhecida: $1";; esac; done
[[ ${EUID} -eq 0 ]] || fail "execute como root"
[[ "${CONTROLLER_URL}" =~ ^https?://[^[:space:]]+$ ]] || fail "Controller URL inválida"; [[ -n "${PAIRING_TOKEN}" ]] || fail "pairing token é obrigatório"
unset CAPIVARA_PAIRING_TOKEN
for cmd in python3 install systemctl; do command -v "$cmd" >/dev/null || fail "comando necessário ausente: $cmd"; done
[[ -n "${PACKAGE_DIR}" ]] || PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; PACKAGE_DIR="$(cd "${PACKAGE_DIR}" && pwd)"

RUNTIME_FILES=(agent.py capabilities.py network_inventory.py update_client.py update_state.py local_cli.py cap_dispatch.py game_data_client.py game_data_executor.py game_data_state.py instance_runtime.py runtime_spec.py runtime_events.py runtime_materialization.py runtime_reconciler.py runtime_lock.py runtime_limits.py runtime_operations.py runtime_health.py runtime_metrics.py observability_client.py configuration_client.py content_client.py backup_client.py broadcast_client.py game_runtime.py provisioning_contract.py provisioning_state.py provisioning_client.py provisioning_executor.py privileged_materialization.py)
for required in manifest.json VERSION agent/common/identity.py agent/privileged/materialize_instance.py agent/policy/49-capivara-agent-instance-units.rules agent/updater/updater.py services/capivara-agent.service services/capivara-agent-update.service services/capivara-agent-update.path services/capivara-agent-materialize@.service; do [[ -f "${PACKAGE_DIR}/${required}" ]] || fail "arquivo obrigatório ausente: ${required}"; done
for file in "${RUNTIME_FILES[@]}"; do [[ -f "${PACKAGE_DIR}/agent/runtime/${file}" ]] || fail "arquivo obrigatório ausente: agent/runtime/${file}"; done
for sub in adapters materializers; do for file in __init__.py base.py registry.py systemd.py; do [[ -f "${PACKAGE_DIR}/agent/runtime/${sub}/${file}" ]] || fail "arquivo obrigatório ausente: agent/runtime/${sub}/${file}"; done; done
for file in __init__.py base.py registry.py dayz.py; do [[ -f "${PACKAGE_DIR}/agent/runtime/profiles/${file}" ]] || fail "arquivo obrigatório ausente: agent/runtime/profiles/${file}"; done
python3 - "${PACKAGE_DIR}" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); manifest=json.loads((root/'manifest.json').read_text())
if manifest.get('kind')!='CapivaraAgentPackage' or manifest.get('platform')!='linux': raise SystemExit('manifest de Agent Linux inválido')
if manifest.get('version')!=(root/'VERSION').read_text().strip(): raise SystemExit('versão do pacote diverge do manifest')
for rel in manifest.get('required_files',[]):
 p=root/rel; expected=(manifest.get('files',{}).get(rel) or {}).get('sha256')
 if not p.is_file() or not expected or hashlib.sha256(p.read_bytes()).hexdigest()!=expected: raise SystemExit(f'arquivo/hash inválido: {rel}')
PY
VERSION=$(tr -d '\r\n' <"${PACKAGE_DIR}/VERSION")
if [[ -e "${CLI_PATH}" || -L "${CLI_PATH}" ]]; then
 EXISTING="$(readlink -f "${CLI_PATH}" 2>/dev/null || true)"; OLD="${INSTALL_ROOT}/runtime/local_cli.py"; NEW="${INSTALL_ROOT}/runtime/cap_dispatch.py"
 [[ "${EXISTING}" == "${OLD}" || "${EXISTING}" == "${NEW}" ]] || fail "${CLI_PATH} já existe e não pertence ao Capivara Agent"
fi
id capivara-agent >/dev/null 2>&1 || useradd --system --home "${STATE_DIR}" --create-home --shell /usr/sbin/nologin capivara-agent
install -d -m 0755 -o root -g root "${INSTALL_ROOT}" "${INSTALL_ROOT}/runtime" "${INSTALL_ROOT}/runtime/adapters" "${INSTALL_ROOT}/runtime/materializers" "${INSTALL_ROOT}/runtime/profiles" "${INSTALL_ROOT}/privileged" "${INSTALL_ROOT}/common" "${INSTALL_ROOT}/updater"
install -d -m 0700 -o capivara-agent -g capivara-agent "${CONFIG_DIR}" "${STATE_DIR}" "${STATE_DIR}/game-data" "${STATE_DIR}/game-data-jobs" "${STATE_DIR}/game-data-jobs/history" "${STATE_DIR}/game-data-state" "${STATE_DIR}/update-history" "${STATE_DIR}/instances" "${STATE_DIR}/instance-results" "${STATE_DIR}/instance-command-history" "${STATE_DIR}/events" "${STATE_DIR}/instance-provisioning" "${STATE_DIR}/instance-provisioning/history" "${STATE_DIR}/instance-workspaces" "${STATE_DIR}/privileged-materialization" "${STATE_DIR}/instance-locks" "${STATE_DIR}/instance-operations" "${STATE_DIR}/metrics"
for file in "${RUNTIME_FILES[@]}"; do mode=0644; case "$file" in agent.py|local_cli.py|cap_dispatch.py|game_data_executor.py|provisioning_executor.py) mode=0755;; esac; install -m "$mode" "${PACKAGE_DIR}/agent/runtime/${file}" "${INSTALL_ROOT}/runtime/${file}"; done
for sub in adapters materializers; do for file in __init__.py base.py registry.py systemd.py; do install -m 0644 "${PACKAGE_DIR}/agent/runtime/${sub}/${file}" "${INSTALL_ROOT}/runtime/${sub}/${file}"; done; done
for file in __init__.py base.py registry.py dayz.py; do install -m 0644 "${PACKAGE_DIR}/agent/runtime/profiles/${file}" "${INSTALL_ROOT}/runtime/profiles/${file}"; done
install -m 0755 "${PACKAGE_DIR}/agent/privileged/materialize_instance.py" "${INSTALL_ROOT}/privileged/materialize_instance.py"
install -m 0755 "${PACKAGE_DIR}/agent/updater/updater.py" "${INSTALL_ROOT}/updater/updater.py"
install -m 0644 "${PACKAGE_DIR}/agent/common/identity.py" "${INSTALL_ROOT}/common/identity.py"; install -m 0644 "${PACKAGE_DIR}/manifest.json" "${INSTALL_ROOT}/manifest.json"; printf '%s\n' "${VERSION}" >"${INSTALL_ROOT}/VERSION"
install -d -m 0755 "${POLKIT_RULES_DIR}"; install -m 0644 "${PACKAGE_DIR}/agent/policy/49-capivara-agent-instance-units.rules" "${POLKIT_RULES_DIR}/49-capivara-agent-instance-units.rules"
install -d -m 0755 "$(dirname "${CLI_PATH}")"; ln -sfn "${INSTALL_ROOT}/runtime/cap_dispatch.py" "${CLI_PATH}"
python3 - "${PACKAGE_DIR}" "${CONFIG_DIR}/agent.json" "${CONTROLLER_URL}" "${PAIRING_TOKEN}" "${VERSION}" <<'PY'
import importlib.util,pathlib,sys
package,config_path,url,token,version=sys.argv[1:]; p=pathlib.Path(package)/'agent/common/identity.py'; s=importlib.util.spec_from_file_location('identity',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); identity=m.generate_local_identity()
config={**identity,'controller_url':url.rstrip('/'),'pairing_token':token,'capivara_version':version,'heartbeat_interval_seconds':30,'reconcile_interval_seconds':15,'reconcile_failure_threshold':3,'reconcile_base_backoff_seconds':15,'reconcile_max_backoff_seconds':300,'runtime_lock_timeout_seconds':5,'provisioning_timeout_seconds':3600,'runtime_start_timeout_seconds':90,'runtime_stop_timeout_seconds':90,'reconcile_timeout_seconds':120,'reconcile_max_retries':5,'degraded_after_seconds':60,'offline_after_seconds':120}; m.write_identity(pathlib.Path(config_path),config)
PY
chown capivara-agent:capivara-agent "${CONFIG_DIR}/agent.json"; chmod 0600 "${CONFIG_DIR}/agent.json"
for file in capivara-agent.service capivara-agent-update.service capivara-agent-update.path capivara-agent-materialize@.service; do install -m 0644 "${PACKAGE_DIR}/services/${file}" "${SYSTEMD_DIR}/${file}"; done
systemctl daemon-reload; systemctl enable --now capivara-agent-update.path; systemctl enable --now capivara-agent.service
log "Agent ${VERSION} instalado com runtime serializado, crash-consistent e observável."
