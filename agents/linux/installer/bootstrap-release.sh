#!/usr/bin/env bash
set -Eeuo pipefail

CONTROLLER_URL=""
PAIRING_TOKEN=""
RELEASE_TAG="${CAPIVARA_RELEASE_TAG:-latest}"
REPO="${CAPIVARA_GITHUB_REPO:-EzequielRibeiro/Distributed-Server-Manager}"
API="${CAPIVARA_GITHUB_API:-https://api.github.com}"
TMP=""

fail(){ printf '[Capivara Agent][ERRO] %s\n' "$*" >&2; exit 1; }
log(){ printf '[Capivara Agent] %s\n' "$*"; }
cleanup(){ [[ -z "${TMP}" || ! -d "${TMP}" ]] || rm -rf -- "${TMP}"; }
trap cleanup EXIT

usage(){ cat <<'EOF'
Uso:
  sudo bootstrap-release.sh --controller-url https://controller.exemplo --pairing-token TOKEN [--version vX.Y.Z]

Baixa exclusivamente um pacote imutável de GitHub Release, valida SHA-256 e
então chama o instalador local contido no próprio pacote.
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
for cmd in curl tar sha256sum python3; do command -v "$cmd" >/dev/null || fail "comando necessário ausente: $cmd"; done

TMP=$(mktemp -d /tmp/capivara-agent-release.XXXXXX)
RELEASE_JSON="${TMP}/release.json"
if [[ "${RELEASE_TAG}" == latest ]]; then
  curl -fsSL -H 'Accept: application/vnd.github+json' "${API}/repos/${REPO}/releases/latest" -o "${RELEASE_JSON}"
else
  curl -fsSL -H 'Accept: application/vnd.github+json' "${API}/repos/${REPO}/releases/tags/${RELEASE_TAG}" -o "${RELEASE_JSON}"
fi

python3 - "${TMP}" "${RELEASE_JSON}" <<'PY'
import json, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
data = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))
assets = data.get('assets') or []
pattern = re.compile(r'^capivara-agent-linux-[0-9].*\.tar\.gz$')
archive = next((a for a in assets if pattern.match(a.get('name',''))), None)
if not archive:
    raise SystemExit('Release sem pacote Linux Agent')
checksum_name = archive['name'] + '.sha256'
checksum = next((a for a in assets if a.get('name') == checksum_name), None)
if not checksum:
    raise SystemExit('Release sem checksum do pacote Linux Agent')
(root / 'urls').write_text(archive['browser_download_url']+'\n'+checksum['browser_download_url']+'\n', encoding='utf-8')
(root / 'names').write_text(archive['name']+'\n'+checksum_name+'\n', encoding='utf-8')
PY

mapfile -t URLS <"${TMP}/urls"
mapfile -t NAMES <"${TMP}/names"
ARCHIVE="${TMP}/${NAMES[0]}"
CHECKSUM="${TMP}/${NAMES[1]}"
log "Baixando pacote Linux Agent de GitHub Release..."
curl -fsSL "${URLS[0]}" -o "${ARCHIVE}"
curl -fsSL "${URLS[1]}" -o "${CHECKSUM}"
EXPECTED=$(awk '{print $1}' "${CHECKSUM}")
ACTUAL=$(sha256sum "${ARCHIVE}" | awk '{print $1}')
[[ -n "${EXPECTED}" && "${EXPECTED}" == "${ACTUAL}" ]] || fail "checksum do pacote Linux Agent inválido"
log "Pacote validado por SHA-256."

mkdir "${TMP}/extract"
tar -xzf "${ARCHIVE}" -C "${TMP}/extract"
PACKAGE_ROOT=$(find "${TMP}/extract" -mindepth 1 -maxdepth 1 -type d -name 'capivara-agent-linux-*' -print -quit)
[[ -n "${PACKAGE_ROOT}" && -x "${PACKAGE_ROOT}/install-agent.sh" ]] || fail "pacote Linux Agent inválido"
exec "${PACKAGE_ROOT}/install-agent.sh" \
  --package-dir "${PACKAGE_ROOT}" \
  --controller-url "${CONTROLLER_URL}" \
  --pairing-token "${PAIRING_TOKEN}"
