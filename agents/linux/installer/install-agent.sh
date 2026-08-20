#!/usr/bin/env bash
set -Eeuo pipefail

CONTROLLER_URL=""
PAIRING_TOKEN=""
RELEASE_TAG="${CAPIVARA_RELEASE_TAG:-latest}"
REPO="${CAPIVARA_GITHUB_REPO:-EzequielRibeiro/Distributed-Server-Manager}"
API="${CAPIVARA_GITHUB_API:-https://api.github.com}"
INSTALL_ROOT="${CAPIVARA_AGENT_ROOT:-/opt/capivara-agent}"
CONFIG_DIR="${CAPIVARA_AGENT_CONFIG_DIR:-/etc/capivara-agent}"
STATE_DIR="${CAPIVARA_AGENT_STATE_DIR:-/var/lib/capivara-agent}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
TMP=""

fail(){ printf '[Capivara Agent][ERRO] %s\n' "$*" >&2; exit 1; }
log(){ printf '[Capivara Agent] %s\n' "$*"; }
cleanup(){ [[ -z "${TMP}" || ! -d "${TMP}" ]] || rm -rf -- "${TMP}"; }
trap cleanup EXIT

usage(){
cat <<'EOF'
Uso:
  sudo install-agent.sh --controller-url https://controller.exemplo --pairing-token TOKEN

O pairing token é usado somente no primeiro registro. Nenhuma senha administrativa
é aceita ou armazenada pelo instalador.
EOF
}

while (( $# )); do
  case "$1" in
    --controller-url) [[ $# -ge 2 ]] || fail "--controller-url requer valor"; CONTROLLER_URL="$2"; shift 2;;
    --pairing-token) [[ $# -ge 2 ]] || fail "--pairing-token requer valor"; PAIRING_TOKEN="$2"; shift 2;;
    --version) [[ $# -ge 2 ]] || fail "--version requer valor"; RELEASE_TAG="$2"; shift 2;;
    --help|-h) usage; exit 0;;
    *) fail "opção desconhecida: $1";;
  esac
done

[[ ${EUID} -eq 0 ]] || fail "execute como root"
[[ "${CONTROLLER_URL}" =~ ^https?://[^[:space:]]+$ ]] || fail "Controller URL inválida"
[[ -n "${PAIRING_TOKEN}" ]] || fail "pairing token é obrigatório"
for cmd in curl tar sha256sum python3 install systemctl; do command -v "$cmd" >/dev/null || fail "comando necessário ausente: $cmd"; done

TMP=$(mktemp -d /tmp/capivara-agent-installer.XXXXXX)
if [[ "${RELEASE_TAG}" == latest ]]; then
  RELEASE_JSON=$(curl -fsSL -H 'Accept: application/vnd.github+json' "${API}/repos/${REPO}/releases/latest")
else
  RELEASE_JSON=$(curl -fsSL -H 'Accept: application/vnd.github+json' "${API}/repos/${REPO}/releases/tags/${RELEASE_TAG}")
fi
python3 - "${TMP}" <<'PY' <<<"${RELEASE_JSON}"
import json,sys,pathlib
root=pathlib.Path(sys.argv[1]); data=json.load(sys.stdin)
assets=data.get('assets') or []
archive=next((a for a in assets if a.get('name','').endswith('.tar.gz') and not a.get('name','').endswith('.sha256')),None)
checksum=next((a for a in assets if a.get('name','').endswith('.tar.gz.sha256')),None)
if not archive or not checksum: raise SystemExit('release sem archive/checksum do Capivara')
(root/'urls').write_text(archive['browser_download_url']+'\n'+checksum['browser_download_url']+'\n',encoding='utf-8')
PY
mapfile -t URLS < "${TMP}/urls"
ARCHIVE="${TMP}/package.tar.gz"; CHECKSUM="${TMP}/package.tar.gz.sha256"
log "Baixando pacote oficial..."
curl -fsSL "${URLS[0]}" -o "${ARCHIVE}"
curl -fsSL "${URLS[1]}" -o "${CHECKSUM}"
EXPECTED=$(awk '{print $1}' "${CHECKSUM}")
ACTUAL=$(sha256sum "${ARCHIVE}" | awk '{print $1}')
[[ "${EXPECTED}" == "${ACTUAL}" ]] || fail "checksum do pacote inválido"
log "Pacote validado por SHA-256."
mkdir "${TMP}/extract"; tar -xzf "${ARCHIVE}" -C "${TMP}/extract"
PACKAGE_ROOT=$(find "${TMP}/extract" -mindepth 1 -maxdepth 1 -type d -name 'capivara-dsm-*' -print -quit)
[[ -n "${PACKAGE_ROOT}" ]] || fail "raiz do pacote não encontrada"
for required in agents/common/identity.py agents/linux/runtime/agent.py agents/linux/services/capivara-agent.service version release-manifest.json; do
  [[ -f "${PACKAGE_ROOT}/${required}" ]] || fail "arquivo obrigatório ausente: ${required}"
done
VERSION=$(tr -d '\r\n' < "${PACKAGE_ROOT}/version")

id capivara-agent >/dev/null 2>&1 || useradd --system --home "${STATE_DIR}" --create-home --shell /usr/sbin/nologin capivara-agent
install -d -m 0755 -o root -g root "${INSTALL_ROOT}" "${INSTALL_ROOT}/runtime" "${INSTALL_ROOT}/common"
install -d -m 0700 -o capivara-agent -g capivara-agent "${CONFIG_DIR}" "${STATE_DIR}"
install -m 0755 "${PACKAGE_ROOT}/agents/linux/runtime/agent.py" "${INSTALL_ROOT}/runtime/agent.py"
install -m 0644 "${PACKAGE_ROOT}/agents/common/identity.py" "${INSTALL_ROOT}/common/identity.py"

python3 - "${PACKAGE_ROOT}" "${CONFIG_DIR}/agent.json" "${CONTROLLER_URL}" "${PAIRING_TOKEN}" "${VERSION}" <<'PY'
import importlib.util,json,os,pathlib,sys
package, config_path, controller_url, token, version = sys.argv[1:]
identity_path=pathlib.Path(package)/'agents/common/identity.py'
spec=importlib.util.spec_from_file_location('capivara_agent_identity', identity_path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
identity=mod.generate_local_identity()
config={**identity,'controller_url':controller_url.rstrip('/'),'pairing_token':token,'capivara_version':version,'heartbeat_interval_seconds':30,'degraded_after_seconds':60,'offline_after_seconds':120}
path=pathlib.Path(config_path); mod.write_identity(path,config)
PY
chown capivara-agent:capivara-agent "${CONFIG_DIR}/agent.json"
chmod 0600 "${CONFIG_DIR}/agent.json"
install -m 0644 "${PACKAGE_ROOT}/agents/linux/services/capivara-agent.service" "${SYSTEMD_DIR}/capivara-agent.service"
systemctl daemon-reload
systemctl enable --now capivara-agent.service
log "Agent instalado. O serviço fará enrollment, removerá o pairing token e iniciará heartbeat."
