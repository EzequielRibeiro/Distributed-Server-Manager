#!/usr/bin/env bash
set -Eeuo pipefail

CONTROLLER_URL=""
PAIRING_TOKEN="${CAPIVARA_PAIRING_TOKEN:-}"
PACKAGE_DIR=""
INSTALL_ROOT="${CAPIVARA_AGENT_ROOT:-/opt/capivara-agent}"
CONFIG_DIR="${CAPIVARA_AGENT_CONFIG_DIR:-/etc/capivara-agent}"
STATE_DIR="${CAPIVARA_AGENT_STATE_DIR:-/var/lib/capivara-agent}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

fail(){ printf '[Capivara Agent][ERRO] %s\n' "$*" >&2; exit 1; }
log(){ printf '[Capivara Agent] %s\n' "$*"; }

usage(){ cat <<'EOF'
Uso:
  sudo ./install-agent.sh --controller-url https://controller.exemplo --pairing-token TOKEN
  sudo ./install-agent.sh --package-dir /caminho/capivara-agent-linux-X.Y.Z --controller-url ... --pairing-token ...

Para automação segura, o token também pode ser fornecido pelo ambiente raiz
CAPIVARA_PAIRING_TOKEN, evitando exposição no argv do processo.

Este instalador opera somente sobre um pacote/diretório local já validado ou
construído a partir do repositório oficial. Ele não clona branch e não baixa código.
EOF
}

while (( $# )); do
  case "$1" in
    --controller-url) [[ $# -ge 2 ]] || fail "--controller-url requer valor"; CONTROLLER_URL="$2"; shift 2;;
    --pairing-token) [[ $# -ge 2 ]] || fail "--pairing-token requer valor"; PAIRING_TOKEN="$2"; shift 2;;
    --package-dir) [[ $# -ge 2 ]] || fail "--package-dir requer valor"; PACKAGE_DIR="$2"; shift 2;;
    --help|-h) usage; exit 0;;
    *) fail "opção desconhecida: $1";;
  esac
done

[[ ${EUID} -eq 0 ]] || fail "execute como root"
[[ "${CONTROLLER_URL}" =~ ^https?://[^[:space:]]+$ ]] || fail "Controller URL inválida"
[[ -n "${PAIRING_TOKEN}" ]] || fail "pairing token é obrigatório"
unset CAPIVARA_PAIRING_TOKEN
for cmd in python3 install systemctl; do command -v "$cmd" >/dev/null || fail "comando necessário ausente: $cmd"; done

if [[ -z "${PACKAGE_DIR}" ]]; then
  PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
PACKAGE_DIR="$(cd "${PACKAGE_DIR}" && pwd)"

for required in \
  manifest.json VERSION \
  agent/common/identity.py \
  agent/runtime/agent.py agent/runtime/capabilities.py agent/runtime/network_inventory.py agent/runtime/update_client.py \
  agent/updater/updater.py \
  services/capivara-agent.service services/capivara-agent-update.service services/capivara-agent-update.path
do
  [[ -f "${PACKAGE_DIR}/${required}" ]] || fail "arquivo obrigatório ausente: ${required}"
done

python3 - "${PACKAGE_DIR}" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
if manifest.get('kind') != 'CapivaraAgentPackage' or manifest.get('platform') != 'linux':
    raise SystemExit('manifest de Agent Linux inválido')
version = (root / 'VERSION').read_text(encoding='utf-8').strip()
if manifest.get('version') != version:
    raise SystemExit('versão do pacote diverge do manifest')
for relative in manifest.get('required_files', []):
    path = root / relative
    if not path.is_file():
        raise SystemExit(f'arquivo obrigatório ausente: {relative}')
    expected = (manifest.get('files', {}).get(relative) or {}).get('sha256')
    if expected:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f'hash interno inválido: {relative}')
PY
VERSION=$(tr -d '\r\n' < "${PACKAGE_DIR}/VERSION")

id capivara-agent >/dev/null 2>&1 || useradd --system --home "${STATE_DIR}" --create-home --shell /usr/sbin/nologin capivara-agent
install -d -m 0755 -o root -g root "${INSTALL_ROOT}" "${INSTALL_ROOT}/runtime" "${INSTALL_ROOT}/common" "${INSTALL_ROOT}/updater"
install -d -m 0700 -o capivara-agent -g capivara-agent "${CONFIG_DIR}" "${STATE_DIR}"
install -m 0755 "${PACKAGE_DIR}/agent/runtime/agent.py" "${INSTALL_ROOT}/runtime/agent.py"
install -m 0644 "${PACKAGE_DIR}/agent/runtime/capabilities.py" "${INSTALL_ROOT}/runtime/capabilities.py"
install -m 0644 "${PACKAGE_DIR}/agent/runtime/network_inventory.py" "${INSTALL_ROOT}/runtime/network_inventory.py"
install -m 0644 "${PACKAGE_DIR}/agent/runtime/update_client.py" "${INSTALL_ROOT}/runtime/update_client.py"
install -m 0755 "${PACKAGE_DIR}/agent/updater/updater.py" "${INSTALL_ROOT}/updater/updater.py"
install -m 0644 "${PACKAGE_DIR}/agent/common/identity.py" "${INSTALL_ROOT}/common/identity.py"
install -m 0644 "${PACKAGE_DIR}/manifest.json" "${INSTALL_ROOT}/manifest.json"
printf '%s\n' "${VERSION}" >"${INSTALL_ROOT}/VERSION"

python3 - "${PACKAGE_DIR}" "${CONFIG_DIR}/agent.json" "${CONTROLLER_URL}" "${PAIRING_TOKEN}" "${VERSION}" <<'PY'
import importlib.util, pathlib, sys
package, config_path, controller_url, token, version = sys.argv[1:]
identity_path = pathlib.Path(package) / 'agent/common/identity.py'
spec = importlib.util.spec_from_file_location('capivara_agent_identity', identity_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
identity = mod.generate_local_identity()
config = {**identity, 'controller_url': controller_url.rstrip('/'), 'pairing_token': token, 'capivara_version': version,
          'heartbeat_interval_seconds': 30, 'degraded_after_seconds': 60, 'offline_after_seconds': 120}
mod.write_identity(pathlib.Path(config_path), config)
PY
chown capivara-agent:capivara-agent "${CONFIG_DIR}/agent.json"
chmod 0600 "${CONFIG_DIR}/agent.json"
install -m 0644 "${PACKAGE_DIR}/services/capivara-agent.service" "${SYSTEMD_DIR}/capivara-agent.service"
install -m 0644 "${PACKAGE_DIR}/services/capivara-agent-update.service" "${SYSTEMD_DIR}/capivara-agent-update.service"
install -m 0644 "${PACKAGE_DIR}/services/capivara-agent-update.path" "${SYSTEMD_DIR}/capivara-agent-update.path"
systemctl daemon-reload
systemctl enable --now capivara-agent-update.path
systemctl enable --now capivara-agent.service
log "Agent ${VERSION} instalado a partir do pacote local. Enrollment, heartbeat e atualização remota estão habilitados."
