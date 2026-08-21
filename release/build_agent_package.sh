#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF="${1:-HEAD}"
OUTPUT_DIR="${2:-${ROOT}/dist}"
fail(){ printf 'Agent package build failed: %s\n' "$*" >&2; exit 1; }
for command_name in git tar gzip sha256sum python3; do command -v "${command_name}" >/dev/null 2>&1 || fail "required command not found: ${command_name}"; done
git -C "${ROOT}" rev-parse --verify "${REF}^{commit}" >/dev/null 2>&1 || fail "invalid Git ref: ${REF}"
COMMIT=$(git -C "${ROOT}" rev-parse "${REF}^{commit}")
VERSION=$(git -C "${ROOT}" show "${REF}:version" | tr -d '\r\n')
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || fail "invalid SemVer: ${VERSION}"
SOURCE_DATE_EPOCH=$(git -C "${ROOT}" show -s --format=%ct "${COMMIT}")
CHANNEL=stable; [[ "${VERSION}" == *-* ]] && CHANNEL=beta
PACKAGE_NAME="capivara-agent-linux-${VERSION}"; ARCHIVE_NAME="${PACKAGE_NAME}.tar.gz"
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/capivara-agent-package.XXXXXX"); PACKAGE_ROOT="${WORK_DIR}/${PACKAGE_NAME}"
cleanup(){ rm -rf -- "${WORK_DIR}"; }; trap cleanup EXIT
mkdir -p "${PACKAGE_ROOT}/agent/common" "${PACKAGE_ROOT}/agent/runtime" "${PACKAGE_ROOT}/agent/updater" "${PACKAGE_ROOT}/services" "${PACKAGE_ROOT}/config"

git -C "${ROOT}" show "${REF}:agents/linux/installer/install-agent.sh" >"${PACKAGE_ROOT}/install-agent.sh"
git -C "${ROOT}" show "${REF}:agents/common/identity.py" >"${PACKAGE_ROOT}/agent/common/identity.py"
for file in agent.py capabilities.py network_inventory.py update_client.py update_state.py local_cli.py game_data_client.py game_data_executor.py game_data_state.py instance_runtime.py; do
  git -C "${ROOT}" show "${REF}:agents/linux/runtime/${file}" >"${PACKAGE_ROOT}/agent/runtime/${file}"
done
git -C "${ROOT}" show "${REF}:agents/linux/updater/updater.py" >"${PACKAGE_ROOT}/agent/updater/updater.py"
for file in capivara-agent.service capivara-agent-update.service capivara-agent-update.path; do git -C "${ROOT}" show "${REF}:agents/linux/services/${file}" >"${PACKAGE_ROOT}/services/${file}"; done
printf '%s\n' "${VERSION}" >"${PACKAGE_ROOT}/VERSION"
printf '%s\n' 'Runtime configuration is created during installation. Pairing secrets are never packaged.' >"${PACKAGE_ROOT}/config/README.md"
chmod 0755 "${PACKAGE_ROOT}/install-agent.sh" "${PACKAGE_ROOT}/agent/runtime/agent.py" "${PACKAGE_ROOT}/agent/runtime/local_cli.py" "${PACKAGE_ROOT}/agent/runtime/game_data_executor.py" "${PACKAGE_ROOT}/agent/updater/updater.py"
find "${PACKAGE_ROOT}/agent" -type f ! -perm -0100 -exec chmod 0644 {} +
chmod 0644 "${PACKAGE_ROOT}/services/"* "${PACKAGE_ROOT}/VERSION" "${PACKAGE_ROOT}/config/README.md"

python3 - "${PACKAGE_ROOT}" "${VERSION}" "${COMMIT}" "${CHANNEL}" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]); version, commit, channel = sys.argv[2:]
required = [
 "install-agent.sh", "agent/common/identity.py",
 "agent/runtime/agent.py", "agent/runtime/capabilities.py", "agent/runtime/network_inventory.py",
 "agent/runtime/update_client.py", "agent/runtime/update_state.py", "agent/runtime/local_cli.py",
 "agent/runtime/game_data_client.py", "agent/runtime/game_data_executor.py", "agent/runtime/game_data_state.py",
 "agent/runtime/instance_runtime.py", "agent/updater/updater.py",
 "services/capivara-agent.service", "services/capivara-agent-update.service", "services/capivara-agent-update.path",
 "VERSION", "config/README.md",
]
files = {}
for relative in required:
    data = (root / relative).read_bytes(); files[relative] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
manifest = {"schema_version":1,"kind":"CapivaraAgentPackage","platform":"linux","version":version,"git_commit":commit,"channel":channel,"required_files":required,"files":files}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
chmod 0644 "${PACKAGE_ROOT}/manifest.json"
mkdir -p "${OUTPUT_DIR}"; OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"; CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"; MANIFEST_PATH="${OUTPUT_DIR}/${PACKAGE_NAME}.manifest.json"
rm -f -- "${ARCHIVE_PATH}" "${CHECKSUM_PATH}" "${MANIFEST_PATH}" "${ARCHIVE_PATH}.minisig"
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 --numeric-owner -cf - -C "${WORK_DIR}" "${PACKAGE_NAME}" | gzip -n >"${ARCHIVE_PATH}"
( cd "${OUTPUT_DIR}"; sha256sum "${ARCHIVE_NAME}" >"${ARCHIVE_NAME}.sha256" )
cp "${PACKAGE_ROOT}/manifest.json" "${MANIFEST_PATH}"
if [[ -n "${CAPIVARA_MINISIGN_SECRET_KEY_FILE:-}" ]]; then
  command -v minisign >/dev/null 2>&1 || fail "minisign key configured but minisign is unavailable"
  [[ -f "${CAPIVARA_MINISIGN_SECRET_KEY_FILE}" ]] || fail "configured minisign secret key file not found"
  minisign -S -s "${CAPIVARA_MINISIGN_SECRET_KEY_FILE}" -m "${ARCHIVE_PATH}" -x "${ARCHIVE_PATH}.minisig"
fi
printf 'Agent package: %s\n' "${ARCHIVE_PATH}"
printf 'Checksum: %s\n' "${CHECKSUM_PATH}"
printf 'Manifest: %s\n' "${MANIFEST_PATH}"
[[ ! -f "${ARCHIVE_PATH}.minisig" ]] || printf 'Signature: %s\n' "${ARCHIVE_PATH}.minisig"
