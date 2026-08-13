#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF="${1:-HEAD}"
OUTPUT_DIR="${2:-${ROOT}/dist}"

fail() {
    printf 'Release build failed: %s\n' "$*" >&2
    exit 1
}

for command_name in git tar gzip sha256sum python3
do
    command -v "${command_name}" >/dev/null 2>&1 || fail "required command not found: ${command_name}"
done

git -C "${ROOT}" rev-parse --verify "${REF}^{commit}" >/dev/null 2>&1 \
    || fail "invalid Git ref: ${REF}"

VERSION=$(git -C "${ROOT}" show "${REF}:version" | tr -d '\r\n')
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] \
    || fail "version is not valid SemVer: ${VERSION}"

COMMIT=$(git -C "${ROOT}" rev-parse "${REF}^{commit}")
SOURCE_DATE_EPOCH=$(git -C "${ROOT}" show -s --format=%ct "${COMMIT}")
PACKAGE_NAME="capivara-dsm-${VERSION}"
ARCHIVE_NAME="${PACKAGE_NAME}.tar.gz"
MANIFEST_NAME="${PACKAGE_NAME}.manifest.json"

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/capivara-release.XXXXXX")
PACKAGE_ROOT="${WORK_DIR}/${PACKAGE_NAME}"

cleanup() {
    if [[ -n "${WORK_DIR:-}" && -d "${WORK_DIR}" && "${WORK_DIR}" == "${TMPDIR:-/tmp}/capivara-release."* ]]
    then
        rm -rf -- "${WORK_DIR}"
    fi
}
trap cleanup EXIT

git -C "${ROOT}" archive --format=tar --prefix="${PACKAGE_NAME}/" "${COMMIT}" \
    | tar -xf - -C "${WORK_DIR}"

[[ -d "${PACKAGE_ROOT}" && "${PACKAGE_ROOT}" == "${WORK_DIR}/"* ]] \
    || fail "unsafe staging directory"

# Development metadata and machine-generated data are not release inputs.
for relative_path in \
    .artifacts .idea .github .gitignore .gitattributes \
    backups cache logs tmp packages instances export import \
    test-failure test-http test-http-atomic tools/steamcmd \
    dashboard/server.py.backup
do
    rm -rf -- "${PACKAGE_ROOT}/${relative_path}"
done

# Keep executable runtime/bootstrap code, but never publish local state.
if [[ -d "${PACKAGE_ROOT}/runtime" ]]
then
    find "${PACKAGE_ROOT}/runtime" -type f \
        ! -name '*.sh' ! -name '*.conf' -delete
    find "${PACKAGE_ROOT}/runtime" -depth -type d -empty -delete
fi
if [[ -d "${PACKAGE_ROOT}/dashboard/state" ]]
then
    find "${PACKAGE_ROOT}/dashboard/state" -type f \
        ! -name 'init_state.sh' -delete
fi
if [[ -d "${PACKAGE_ROOT}/backup" ]]
then
    find "${PACKAGE_ROOT}/backup" -type f \
        ! -name '*.sh' -delete
fi

REQUIRED_FILES=(
    version
    install.sh
    update.sh
    bin/dsm
    core/bootstrap.sh
    dashboard/server.py
    database/manager.py
    database/migrations/001_initial.sql
    installer/catalog.sh
    installer/compatibility_resolver.sh
    catalog/v2/schemas/runtime-definition.schema.json
    systemd/dsm-dashboard.service
)
for relative_path in "${REQUIRED_FILES[@]}"
do
    [[ -f "${PACKAGE_ROOT}/${relative_path}" ]] \
        || fail "required release file missing: ${relative_path}"
done

FILE_COUNT=$(find "${PACKAGE_ROOT}" -type f | wc -l | tr -d ' ')
CREATED_AT=$(python3 - "${SOURCE_DATE_EPOCH}" <<'PY'
import datetime
import sys

epoch = int(sys.argv[1])
print(datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat().replace("+00:00", "Z"))
PY
)

python3 - \
    "${PACKAGE_ROOT}/release-manifest.json" \
    "${VERSION}" "${COMMIT}" "${CREATED_AT}" "${ARCHIVE_NAME}" "${FILE_COUNT}" <<'PY'
import json
import pathlib
import sys

target, version, commit, created_at, archive, file_count = sys.argv[1:]
manifest = {
    "schema_version": 1,
    "kind": "CapivaraReleaseManifest",
    "name": "capivara-dsm",
    "version": version,
    "git_commit": commit,
    "created_at": created_at,
    "archive": archive,
    "file_count": int(file_count) + 1,
    "required_files": [
        "version",
        "install.sh",
        "update.sh",
        "bin/dsm",
        "core/bootstrap.sh",
        "dashboard/server.py",
        "database/manager.py",
        "database/migrations/001_initial.sql",
        "installer/catalog.sh",
        "installer/compatibility_resolver.sh",
        "catalog/v2/schemas/runtime-definition.schema.json",
        "systemd/dsm-dashboard.service",
    ],
}
pathlib.Path(target).write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
    newline="\n",
)
PY
chmod 644 "${PACKAGE_ROOT}/release-manifest.json"

mkdir -p "${OUTPUT_DIR}"
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"
MANIFEST_PATH="${OUTPUT_DIR}/${MANIFEST_NAME}"
CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"

rm -f -- "${ARCHIVE_PATH}" "${MANIFEST_PATH}" "${CHECKSUM_PATH}"
tar --sort=name \
    --mtime="@${SOURCE_DATE_EPOCH}" \
    --owner=0 --group=0 --numeric-owner \
    -cf - -C "${WORK_DIR}" "${PACKAGE_NAME}" \
    | gzip -n >"${ARCHIVE_PATH}"

cp "${PACKAGE_ROOT}/release-manifest.json" "${MANIFEST_PATH}"
(
    cd "${OUTPUT_DIR}"
    sha256sum "${ARCHIVE_NAME}" >"${ARCHIVE_NAME}.sha256"
)

printf 'Release package: %s\n' "${ARCHIVE_PATH}"
printf 'Manifest: %s\n' "${MANIFEST_PATH}"
printf 'Checksum: %s\n' "${CHECKSUM_PATH}"
