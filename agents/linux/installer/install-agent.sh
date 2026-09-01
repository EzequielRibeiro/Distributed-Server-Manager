#!/usr/bin/env bash
set -Eeuo pipefail

CONTROLLER_URL=""; CONTROLLER_CA_FILE=""; PAIRING_TOKEN="${CAPIVARA_PAIRING_TOKEN:-}"; PACKAGE_DIR=""
INSTALL_ROOT="${CAPIVARA_AGENT_ROOT:-/opt/capivara-agent}"; CONFIG_DIR="${CAPIVARA_AGENT_CONFIG_DIR:-/etc/capivara-agent}"
STATE_DIR="${CAPIVARA_AGENT_STATE_DIR:-/var/lib/capivara-agent}"; INSTANCE_STORAGE_ROOT="${CAPIVARA_INSTANCE_STORAGE_ROOT:-/var/lib/capivara-instances}"; SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
POLKIT_RULES_DIR="${CAPIVARA_POLKIT_RULES_DIR:-/etc/polkit-1/rules.d}"; CLI_PATH="${CAPIVARA_AGENT_CLI_PATH:-/usr/local/bin/cap}"
fail(){ printf '[Capivara Agent][ERRO] %s\n' "$*" >&2; exit 1; }; log(){ printf '[Capivara Agent] %s\n' "$*"; }
usage(){ cat <<'EOF'
Uso:
  sudo ./install-agent.sh --controller-url https://controller.exemplo:18080 --pairing-token TOKEN [opções]
  sudo ./install-agent.sh --pairing-token TOKEN [opções]   # pergunta o endpoint em terminal interativo

Opções:
  --controller-url URL       Endpoint do Controller alcançável por este Agent.
                             Ex.: http://192.168.15.35:8080 ou https://controller.exemplo:18080
  --controller-ca-file FILE  CA/certificado PEM privado do Controller para HTTPS local.
                             Não é necessário para Let's Encrypt/CA pública.
  --pairing-token TOKEN      Token de pareamento do Agent.
  --instance-storage-root P  Diretório raiz das instâncias.
  --package-dir DIR          Pacote do Agent a instalar.

Importante:
  Em acesso externo informe a porta pública/NAT que o Agent realmente alcança.
  Ex.: roteador 18080 -> Controller 8080 => o Agent usa :18080.
  O instalador nunca sobrescreve /etc/capivara-agent/agent.json existente.
  Para atualizar use o updater. Para recuperar credencial/identidade use o fluxo administrativo de relink.
EOF
}
while (( $# )); do case "$1" in
  --controller-url) [[ $# -ge 2 ]] || fail "--controller-url requer valor"; CONTROLLER_URL="$2"; shift 2;;
  --controller-ca-file) [[ $# -ge 2 ]] || fail "--controller-ca-file requer valor"; CONTROLLER_CA_FILE="$2"; shift 2;;
  --pairing-token) [[ $# -ge 2 ]] || fail "--pairing-token requer valor"; PAIRING_TOKEN="$2"; shift 2;;
  --instance-storage-root) [[ $# -ge 2 ]] || fail "--instance-storage-root requer valor"; INSTANCE_STORAGE_ROOT="$2"; shift 2;;
  --package-dir) [[ $# -ge 2 ]] || fail "--package-dir requer valor"; PACKAGE_DIR="$2"; shift 2;;
  --help|-h) usage; exit 0;; *) fail "opção desconhecida: $1";; esac; done
[[ ${EUID} -eq 0 ]] || fail "execute como root"

CONFIG_PATH="${CONFIG_DIR}/agent.json"
if [[ -e "${CONFIG_PATH}" || -L "${CONFIG_PATH}" ]]; then
  fail "${CONFIG_PATH} já existe. O instalador recusou sobrescrever a identidade persistida do Agent. Use o updater para atualização ou o fluxo administrativo de relink para recuperação; remova/mova esse arquivo somente após confirmar uma reinstalação realmente nova."
fi

normalize_controller_url(){
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
value=sys.argv[1].strip()
try:
    parsed=urlsplit(value)
    port=parsed.port
except ValueError as exc:
    raise SystemExit(f"Controller URL inválida: {exc}")
if parsed.scheme not in {"http","https"} or not parsed.hostname:
    raise SystemExit("Controller URL deve usar http:// ou https:// e conter host/IP")
if port is not None and not 1 <= port <= 65535:
    raise SystemExit("porta do Controller deve estar entre 1 e 65535")
if parsed.username or parsed.password or parsed.query or parsed.fragment:
    raise SystemExit("Controller URL não deve conter credenciais, query ou fragmento")
path=parsed.path.rstrip("/")
print(urlunsplit((parsed.scheme,parsed.netloc,path,"","")))
PY
}

prompt_controller_url(){
  local access choice host port protocol default_port
  cat <<'EOF'

Como este Agent acessará o Controller?
  1) Rede local / VPN
  2) Internet / acesso externo
EOF
  read -r -p 'Seleção [1]: ' access
  access="${access:-1}"
  case "${access}" in 1|2) ;; *) fail "seleção inválida; use 1 ou 2" ;; esac

  if [[ "${access}" == "1" ]]; then
    read -r -p 'Endereço/IP do Controller: ' host
    read -r -p 'Porta alcançável [8080]: ' port
    port="${port:-8080}"
    cat <<'EOF'
Protocolo:
  1) HTTP
  2) HTTPS
EOF
    read -r -p 'Seleção [1]: ' choice
    choice="${choice:-1}"
  else
    read -r -p 'Endereço público ou DNS do Controller: ' host
    read -r -p 'Porta externa/alcançável [18080]: ' port
    port="${port:-18080}"
    cat <<'EOF'
Protocolo:
  1) HTTPS (recomendado para Internet)
  2) HTTP
EOF
    read -r -p 'Seleção [1]: ' choice
    choice="${choice:-1}"
  fi
  [[ -n "${host}" ]] || fail "endereço do Controller é obrigatório"
  [[ "${port}" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) || fail "porta inválida: ${port}"
  if [[ "${access}" == "1" ]]; then
    case "${choice}" in 1) protocol=http ;; 2) protocol=https ;; *) fail "protocolo inválido" ;; esac
  else
    case "${choice}" in 1) protocol=https ;; 2) protocol=http ;; *) fail "protocolo inválido" ;; esac
  fi
  CONTROLLER_URL="${protocol}://${host}:${port}"
  log "Endpoint configurado para o Agent: ${CONTROLLER_URL}"
}

if [[ -z "${CONTROLLER_URL}" ]]; then
  if [[ -t 0 ]]; then
    prompt_controller_url
  else
    fail "--controller-url é obrigatório em instalação não interativa"
  fi
fi
CONTROLLER_URL="$(normalize_controller_url "${CONTROLLER_URL}")" || fail "Controller URL inválida"
[[ -n "${PAIRING_TOKEN}" ]] || fail "pairing token é obrigatório"
[[ "${INSTANCE_STORAGE_ROOT}" == /* ]] || fail "instance storage root deve ser um caminho absoluto"
[[ "${INSTANCE_STORAGE_ROOT}" != "/" ]] || fail "instance storage root não pode ser /"
[[ "${INSTANCE_STORAGE_ROOT}" != *$'\n'* && "${INSTANCE_STORAGE_ROOT}" != *$'\r'* ]] || fail "instance storage root inválido"
unset CAPIVARA_PAIRING_TOKEN
install_runtime_dependencies(){
  local machine
  machine="$(uname -m)"
  [[ "${machine}" == "x86_64" || "${machine}" == "amd64" ]] || { log "Arquitetura ${machine}: dependências SteamCMD de 32 bits não são aplicáveis."; return 0; }
  if command -v apt-get >/dev/null 2>&1; then
    log "Validando dependências do Agent e compatibilidade SteamCMD..."
    DEBIAN_FRONTEND=noninteractive apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates libc6-i386 lib32gcc-s1 lib32stdc++6
  elif command -v dnf >/dev/null 2>&1; then dnf install -y ca-certificates glibc.i686 libgcc.i686 libstdc++.i686
  elif command -v yum >/dev/null 2>&1; then yum install -y ca-certificates glibc.i686 libgcc.i686 libstdc++6.i686
  elif command -v zypper >/dev/null 2>&1; then zypper --non-interactive install ca-certificates glibc-32bit libgcc_s1-32bit libstdc++6-32bit
  else log "Gerenciador de pacotes não reconhecido; dependências opcionais serão reportadas pelo diagnóstico do Agent."; fi
}
install_controller_ca(){
  [[ -n "${CONTROLLER_CA_FILE}" ]] || return 0
  [[ "${CONTROLLER_URL}" == https://* ]] || fail "--controller-ca-file só pode ser usado com Controller HTTPS"
  [[ -f "${CONTROLLER_CA_FILE}" ]] || fail "CA do Controller não encontrada: ${CONTROLLER_CA_FILE}"
  grep -q 'BEGIN CERTIFICATE' "${CONTROLLER_CA_FILE}" || fail "CA do Controller deve ser um certificado PEM"
  if command -v update-ca-certificates >/dev/null 2>&1; then
    install -m 0644 "${CONTROLLER_CA_FILE}" /usr/local/share/ca-certificates/capivara-controller.crt
    update-ca-certificates >/dev/null
  elif command -v update-ca-trust >/dev/null 2>&1; then
    install -d -m 0755 /etc/pki/ca-trust/source/anchors
    install -m 0644 "${CONTROLLER_CA_FILE}" /etc/pki/ca-trust/source/anchors/capivara-controller.crt
    update-ca-trust extract >/dev/null
  else
    fail "não foi possível atualizar a trust store do sistema"
  fi
  log "CA privada do Controller adicionada à trust store do Linux."
}
install_runtime_dependencies
install_controller_ca
for cmd in python3 install systemctl; do command -v "$cmd" >/dev/null || fail "comando necessário ausente: $cmd"; done
[[ -n "${PACKAGE_DIR}" ]] || PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; PACKAGE_DIR="$(cd "${PACKAGE_DIR}" && pwd)"

mapfile -t RUNTIME_FILES < <(
  find "${PACKAGE_DIR}/agent/runtime" \
    -maxdepth 1 \
    -type f \
    -name '*.py' \
    -printf '%f\n' \
    | LC_ALL=C sort
)
((${#RUNTIME_FILES[@]} > 0)) || fail "nenhum módulo Python encontrado em agent/runtime"
for required in manifest.json VERSION agent/common/identity.py agent/privileged/materialize_instance.py agent/privileged/reconcile_runtime_identity.py agent/policy/49-capivara-agent-instance-units.rules agent/updater/updater.py services/capivara-agent.service services/capivara-agent-update.service services/capivara-agent-update.path services/capivara-agent-materialize@.service services/capivara-agent-runtime-identity.service; do [[ -f "${PACKAGE_DIR}/${required}" ]] || fail "arquivo obrigatório ausente: ${required}"; done
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
if [[ -e "${CLI_PATH}" || -L "${CLI_PATH}" ]]; then EXISTING="$(readlink -f "${CLI_PATH}" 2>/dev/null || true)"; OLD="${INSTALL_ROOT}/runtime/local_cli.py"; NEW="${INSTALL_ROOT}/runtime/cap_dispatch.py"; [[ "${EXISTING}" == "${OLD}" || "${EXISTING}" == "${NEW}" ]] || fail "${CLI_PATH} já existe e não pertence ao Capivara Agent"; fi
id capivara-agent >/dev/null 2>&1 || useradd --system --home "${STATE_DIR}" --create-home --shell /usr/sbin/nologin capivara-agent
install -d -m 0755 -o root -g root "${INSTALL_ROOT}" "${INSTALL_ROOT}/runtime" "${INSTALL_ROOT}/runtime/adapters" "${INSTALL_ROOT}/runtime/materializers" "${INSTALL_ROOT}/runtime/profiles" "${INSTALL_ROOT}/privileged" "${INSTALL_ROOT}/common" "${INSTALL_ROOT}/updater"
install -d -m 0711 -o root -g root "${INSTANCE_STORAGE_ROOT}"
install -d -m 0700 -o capivara-agent -g capivara-agent "${CONFIG_DIR}" "${STATE_DIR}" "${STATE_DIR}/game-data" "${STATE_DIR}/game-data-jobs" "${STATE_DIR}/game-data-jobs/history" "${STATE_DIR}/game-data-state" "${STATE_DIR}/update-history" "${STATE_DIR}/instances" "${STATE_DIR}/instance-results" "${STATE_DIR}/instance-command-history" "${STATE_DIR}/events" "${STATE_DIR}/instance-provisioning" "${STATE_DIR}/instance-provisioning/history" "${STATE_DIR}/instance-workspaces" "${STATE_DIR}/privileged-materialization" "${STATE_DIR}/instance-locks" "${STATE_DIR}/instance-operations" "${STATE_DIR}/metrics" "${STATE_DIR}/storage-pool-migrations" "${STATE_DIR}/storage-pool-migrations/history"
for file in "${RUNTIME_FILES[@]}"; do mode=0644; case "$file" in agent.py|local_cli.py|cap_dispatch.py|controller_cli.py|game_data_executor.py|provisioning_executor.py|storage_pool_migration_executor.py) mode=0755;; esac; install -m "$mode" "${PACKAGE_DIR}/agent/runtime/${file}" "${INSTALL_ROOT}/runtime/${file}"; done
for sub in adapters materializers; do for file in __init__.py base.py registry.py systemd.py; do install -m 0644 "${PACKAGE_DIR}/agent/runtime/${sub}/${file}" "${INSTALL_ROOT}/runtime/${sub}/${file}"; done; done
for file in __init__.py base.py registry.py dayz.py; do install -m 0644 "${PACKAGE_DIR}/agent/runtime/profiles/${file}" "${INSTALL_ROOT}/runtime/profiles/${file}"; done
install -m 0755 "${PACKAGE_DIR}/agent/privileged/materialize_instance.py" "${INSTALL_ROOT}/privileged/materialize_instance.py"
install -m 0755 "${PACKAGE_DIR}/agent/privileged/reconcile_runtime_identity.py" "${INSTALL_ROOT}/privileged/reconcile_runtime_identity.py"
install -m 0755 "${PACKAGE_DIR}/agent/updater/updater.py" "${INSTALL_ROOT}/updater/updater.py"
install -m 0644 "${PACKAGE_DIR}/agent/common/identity.py" "${INSTALL_ROOT}/common/identity.py"; install -m 0644 "${PACKAGE_DIR}/manifest.json" "${INSTALL_ROOT}/manifest.json"; printf '%s\n' "${VERSION}" >"${INSTALL_ROOT}/VERSION"
install -d -m 0755 "${POLKIT_RULES_DIR}"; install -m 0644 "${PACKAGE_DIR}/agent/policy/49-capivara-agent-instance-units.rules" "${POLKIT_RULES_DIR}/49-capivara-agent-instance-units.rules"
install -d -m 0755 "$(dirname "${CLI_PATH}")"; ln -sfn "${INSTALL_ROOT}/runtime/cap_dispatch.py" "${CLI_PATH}"
python3 - "${PACKAGE_DIR}" "${CONFIG_DIR}/agent.json" "${CONTROLLER_URL}" "${PAIRING_TOKEN}" "${VERSION}" "${INSTANCE_STORAGE_ROOT}" <<'PY'
import importlib.util,pathlib,sys
package,config_path,url,token,version,instance_storage_root=sys.argv[1:]; p=pathlib.Path(package)/'agent/common/identity.py'; s=importlib.util.spec_from_file_location('identity',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); identity=m.generate_local_identity()
config={**identity,'controller_url':url.rstrip('/'),'pairing_token':token,'capivara_version':version,'instance_storage_root':str(pathlib.Path(instance_storage_root).resolve()),'heartbeat_interval_seconds':30,'reconcile_interval_seconds':15,'reconcile_failure_threshold':3,'reconcile_base_backoff_seconds':15,'reconcile_max_backoff_seconds':300,'runtime_lock_timeout_seconds':5,'provisioning_timeout_seconds':3600,'runtime_start_timeout_seconds':90,'runtime_stop_timeout_seconds':90,'reconcile_timeout_seconds':120,'reconcile_max_retries':5,'degraded_after_seconds':60,'offline_after_seconds':120}; m.write_identity(pathlib.Path(config_path),config)
PY
chown capivara-agent:capivara-agent "${CONFIG_DIR}/agent.json"; chmod 0600 "${CONFIG_DIR}/agent.json"

log "Testando conectividade com o Controller antes do pareamento..."
if ! CAPIVARA_AGENT_CONFIG="${CONFIG_DIR}/agent.json" python3 "${INSTALL_ROOT}/runtime/controller_cli.py" test "${CONTROLLER_URL}" --timeout 5; then
  fail "Controller não está alcançável em ${CONTROLLER_URL}. Verifique DNS/IP, porta pública/NAT, firewall e protocolo TLS/HTTP."
fi

for file in capivara-agent.service capivara-agent-update.service capivara-agent-update.path capivara-agent-materialize@.service capivara-agent-runtime-identity.service; do install -m 0644 "${PACKAGE_DIR}/services/${file}" "${SYSTEMD_DIR}/${file}"; done
systemctl daemon-reload
systemctl start capivara-agent-runtime-identity.service
systemctl enable --now capivara-agent-update.path
systemctl enable --now capivara-agent.service
log "Agent ${VERSION} instalado com runtime serializado, crash-consistent e observável."
log "Controller: ${CONTROLLER_URL}"
log "Storage de instâncias: ${INSTANCE_STORAGE_ROOT}"
