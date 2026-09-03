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
mkdir -p "${PACKAGE_ROOT}/agent/common" "${PACKAGE_ROOT}/agent/runtime" "${PACKAGE_ROOT}/agent/privileged" "${PACKAGE_ROOT}/agent/updater" "${PACKAGE_ROOT}/agent/policy" "${PACKAGE_ROOT}/services" "${PACKAGE_ROOT}/config"
copy(){ mkdir -p "$(dirname "${PACKAGE_ROOT}/$2")"; git -C "${ROOT}" show "${REF}:$1" >"${PACKAGE_ROOT}/$2"; }

copy agents/linux/installer/install-agent.sh install-agent.sh
copy agents/common/identity.py agent/common/identity.py

# Package every Python module below agents/linux/runtime. The Agent installer and
# updater also discover these modules dynamically, keeping source/package/install
# parity when a new game profile or typed bootstrap helper is introduced.
mapfile -t RUNTIME_SOURCES < <(
  git -C "${ROOT}" ls-tree -r --name-only "${REF}" -- agents/linux/runtime |
    awk '/\.py$/ {print}' |
    LC_ALL=C sort
)
((${#RUNTIME_SOURCES[@]} > 0)) || fail "no Linux runtime Python modules found"
for source in "${RUNTIME_SOURCES[@]}"; do
  relative="${source#agents/linux/runtime/}"
  copy "${source}" "agent/runtime/${relative}"
done

copy agents/linux/privileged/materialize_instance.py agent/privileged/materialize_instance.py
copy agents/linux/privileged/reconcile_runtime_identity.py agent/privileged/reconcile_runtime_identity.py
copy agents/linux/privileged/uninstall_agent.py agent/privileged/uninstall_agent.py
copy agents/linux/policy/49-capivara-agent-instance-units.rules agent/policy/49-capivara-agent-instance-units.rules
copy agents/linux/updater/updater.py agent/updater/updater.py
for file in capivara-agent.service capivara-agent-update.service capivara-agent-update.path capivara-agent-materialize@.service capivara-agent-runtime-identity.service capivara-agent-uninstall.service capivara-agent-uninstall.path; do copy "agents/linux/services/${file}" "services/${file}"; done
printf '%s\n' "${VERSION}" >"${PACKAGE_ROOT}/VERSION"
printf '%s\n' 'Runtime configuration is created during installation. Pairing secrets are never packaged.' >"${PACKAGE_ROOT}/config/README.md"
chmod 0755 "${PACKAGE_ROOT}/install-agent.sh"
for executable in agent.py local_cli.py controller_cli.py relink_cli.py cap_dispatch.py game_data_executor.py provisioning_executor.py storage_pool_migration_executor.py; do
  [[ ! -f "${PACKAGE_ROOT}/agent/runtime/${executable}" ]] || chmod 0755 "${PACKAGE_ROOT}/agent/runtime/${executable}"
done
chmod 0755 "${PACKAGE_ROOT}/agent/privileged/materialize_instance.py" "${PACKAGE_ROOT}/agent/privileged/reconcile_runtime_identity.py" "${PACKAGE_ROOT}/agent/privileged/uninstall_agent.py" "${PACKAGE_ROOT}/agent/updater/updater.py"
find "${PACKAGE_ROOT}/agent" -type f ! -perm -0100 -exec chmod 0644 {} +
chmod 0644 "${PACKAGE_ROOT}/services/"* "${PACKAGE_ROOT}/VERSION" "${PACKAGE_ROOT}/config/README.md"
python3 - "${PACKAGE_ROOT}" "${VERSION}" "${COMMIT}" "${CHANNEL}" <<'PY'
import hashlib, json, pathlib, sys
root=pathlib.Path(sys.argv[1]);version,commit,channel=sys.argv[2:]
required=sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='manifest.json')
files={relative:{"sha256":hashlib.sha256((root/relative).read_bytes()).hexdigest(),"size":(root/relative).stat().st_size} for relative in required}
manifest={"schema_version":1,"kind":"CapivaraAgentPackage","platform":"linux","version":version,"git_commit":commit,"channel":channel,"required_files":required,"files":files}
(root/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
PY
chmod 0644 "${PACKAGE_ROOT}/manifest.json"
mkdir -p "${OUTPUT_DIR}"; OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"; CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"; MANIFEST_PATH="${OUTPUT_DIR}/${PACKAGE_NAME}.manifest.json"
rm -f -- "${ARCHIVE_PATH}" "${CHECKSUM_PATH}" "${MANIFEST_PATH}" "${ARCHIVE_PATH}.minisig"
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 --numeric-owner -cf - -C "${WORK_DIR}" "${PACKAGE_NAME}" | gzip -n >"${ARCHIVE_PATH}"
(cd "${OUTPUT_DIR}" && sha256sum "${ARCHIVE_NAME}" >"${ARCHIVE_NAME}.sha256")
cp "${PACKAGE_ROOT}/manifest.json" "${MANIFEST_PATH}"
if [[ -n "${CAPIVARA_MINISIGN_SECRET_KEY_FILE:-}" ]]; then command -v minisign >/dev/null 2>&1 || fail "minisign key configured but minisign is unavailable"; [[ -f "${CAPIVARA_MINISIGN_SECRET_KEY_FILE}" ]] || fail "configured minisign secret key file not found"; minisign -S -s "${CAPIVARA_MINISIGN_SECRET_KEY_FILE}" -m "${ARCHIVE_PATH}" -x "${ARCHIVE_PATH}.minisig"; fi
printf 'Agent package: %s\nChecksum: %s\nManifest: %s\n' "${ARCHIVE_PATH}" "${CHECKSUM_PATH}" "${MANIFEST_PATH}"
[[ ! -f "${ARCHIVE_PATH}.minisig" ]] || printf 'Signature: %s\n' "${ARCHIVE_PATH}.minisig"
