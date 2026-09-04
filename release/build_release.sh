#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REF="${1:-HEAD}"
OUTPUT_DIR="${2:-${ROOT}/dist}"

fail() {
    printf 'Release build failed: %s\n' "$*" >&2
    exit 1
}

for command_name in git tar gzip sha256sum
do
    command -v "${command_name}" >/dev/null 2>&1 ||
        fail "required command not found: ${command_name}"
done

resolve_python3()
{
    local candidate
    for candidate in python3 python
    do
        command -v "${candidate}" >/dev/null 2>&1 || continue
        if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1
        then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done
    fail "required Python 3 interpreter not found"
}

PYTHON_BIN="$(resolve_python3)"

git -C "${ROOT}" rev-parse --verify "${REF}^{commit}" >/dev/null 2>&1 || fail "invalid Git ref: ${REF}"
VERSION=$(git -C "${ROOT}" show "${REF}:version" | tr -d '\r\n')
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || fail "version is not valid SemVer: ${VERSION}"

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

git -C "${ROOT}" archive --format=tar --prefix="${PACKAGE_NAME}/" "${COMMIT}" | tar -xf - -C "${WORK_DIR}"
[[ -d "${PACKAGE_ROOT}" && "${PACKAGE_ROOT}" == "${WORK_DIR}/"* ]] || fail "unsafe staging directory"

# Hotfix release packaging guard for updater rollback systemd rendering.
"${PYTHON_BIN}" - "${PACKAGE_ROOT}/update.sh" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '''        do
            [[ -e "${UNIT_TEMPLATE}" ]] || continue
            cp -f "${UNIT_TEMPLATE}" "${SYSTEMD_DIR}/"
        done
    fi
    # Atualizar Systemd | Update Systemd
    echo
    echo "Recarregando Systemd..."
'''
new = '''        do
            [[ -e "${UNIT_TEMPLATE}" ]] || continue
            cp -f "${UNIT_TEMPLATE}" "${SYSTEMD_DIR}/"
        done

        # Rollback restores source templates, so render the runtime account
        # before systemd sees the restored units.
        for UNIT_TEMPLATE in \\
            "${SYSTEMD_DIR}/"dsm-*.service \\
            "${SYSTEMD_DIR}/"dsm-*.timer
        do
            [[ -e "${UNIT_TEMPLATE}" ]] || continue
            sed -i \\
                -e "s|{{DSM_USER}}|${DSM_USER}|g" \\
                -e "s|{{DSM_GROUP}}|${DSM_GROUP}|g" \\
                "${UNIT_TEMPLATE}"
        done

        if grep -RqsE '\\{\\{DSM_(USER|GROUP)\\}\\}' \\
            "${SYSTEMD_DIR}/"dsm-*.service \\
            "${SYSTEMD_DIR}/"dsm-*.timer 2>/dev/null
        then
            echo "[ERROR] Rollback deixou placeholders DSM em unidades systemd." >&2
            echo "[ERROR] Rollback left DSM placeholders in systemd units." >&2
            return 1
        fi
    fi
    # Atualizar Systemd | Update Systemd
    echo
    echo "Recarregando Systemd..."
'''
if "Rollback left DSM placeholders in systemd units" not in text:
    if old not in text:
        raise SystemExit("release hotfix anchor not found in update.sh")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
PY

grep -q 'Rollback left DSM placeholders in systemd units' "${PACKAGE_ROOT}/update.sh" || fail "rollback systemd rendering hotfix missing from packaged update.sh"
bash -n "${PACKAGE_ROOT}/update.sh" || fail "packaged update.sh failed syntax validation after rollback hotfix"

# Hotfix Database Baseline v2 preflight classification. Once a validated
# versioned ledger exists, checksum drift between consolidated baselines is
# acceptable when the ledger is already fully reconciled, or when all pending
# upgrades are registered for the target release.
"${PYTHON_BIN}" - "${PACKAGE_ROOT}/update-manager/process-guard.sh" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '''# Once a valid ledger exists, a checksum change is advanced only through the
# target release's registered additive upgrades.
if ledger_present:
    raise SystemExit(0 if pending else 1)
'''
new = '''# Once a valid ledger exists, compatibility is governed by the versioned
# upgrade ledger rather than historical consolidated-baseline checksums.
# A fully reconciled ledger is already compatible; otherwise every pending
# upgrade was validated above against this target release's registry.
if ledger_present:
    current_version = payload.get("upgrade_version")
    latest_version = payload.get("upgrade_latest")
    if not isinstance(current_version, int) or not isinstance(latest_version, int):
        raise SystemExit(1)
    if current_version < 0 or current_version > latest_version:
        raise SystemExit(1)
    if not pending and current_version == latest_version:
        raise SystemExit(0)
    raise SystemExit(0 if pending else 1)
'''
if old not in text:
    raise SystemExit("Baseline v2 preflight hotfix anchor not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8", newline="\n")
PY

bash -n "${PACKAGE_ROOT}/update-manager/process-guard.sh" || fail "packaged process-guard.sh failed syntax validation"
grep -q 'fully reconciled ledger is already compatible' "${PACKAGE_ROOT}/update-manager/process-guard.sh" || fail "Baseline v2 preflight hotfix missing from package"

# Reproduce the PostgreSQL state that blocked v2.0.23: checksum drift with a
# complete v5 ledger and no pending upgrades must be accepted. Prevent Python
# bytecode generation so the release archive remains reproducible.
PAYLOAD='{"schema_version":2,"kind":"DatabaseCheck","driver":"postgresql","connected":true,"initialized":true,"health":"error","baseline":"capivara-baseline-v2","baseline_checksum":"4e80e02a984d13199d7c9372b4828d1f2b0c1d35a77c33a2e35a531c7340c6ec","expected_baseline":"capivara-baseline-v2","expected_checksum":"3f7607066465a6ee45bde521821543b37a5797e262fdff4fad6cf9bcaae05027","checksum_matches":false,"missing_tables":[],"upgrade_ledger":true,"upgrade_version":5,"upgrade_latest":5,"pending_upgrades":[],"upgrade_error":null,"valid":false}'
if ! PYTHONDONTWRITEBYTECODE=1 PAYLOAD="${PAYLOAD}" TARGET_ROOT="${PACKAGE_ROOT}" bash -c 'source "$TARGET_ROOT/update-manager/process-guard.sh"; process_guard_database_check_is_upgradeable "$PAYLOAD" "$TARGET_ROOT"'
then
    fail "Baseline v2 reconciled-ledger regression payload was rejected"
fi

# Development metadata and machine-generated data are not release inputs.
for relative_path in \
    .artifacts .idea .github .gitignore .gitattributes \
    backups cache logs tmp packages instances export import \
    test-failure test-http test-http-atomic tools/steamcmd \
    dashboard/server.py.backup
do
    rm -rf -- "${PACKAGE_ROOT}/${relative_path}"
done

if [[ -d "${PACKAGE_ROOT}/runtime" ]]; then
    find "${PACKAGE_ROOT}/runtime" -type f ! -name '*.sh' ! -name '*.conf' -delete
    find "${PACKAGE_ROOT}/runtime" -depth -type d -empty -delete
fi
if [[ -d "${PACKAGE_ROOT}/dashboard/state" ]]; then
    find "${PACKAGE_ROOT}/dashboard/state" -type f ! -name 'init_state.sh' -delete
fi
if [[ -d "${PACKAGE_ROOT}/backup" ]]; then
    find "${PACKAGE_ROOT}/backup" -type f ! -name '*.sh' -delete
fi

REQUIRED_FILES=(
    version
    install.sh
    update.sh
    bin/dsm
    core/bootstrap.sh
    dashboard/server.py
    dashboard/server_part8.py
    database/manager.py
    database/runtime_backend.py
    database/operations.py
    database/schemas/sqlite.sql
    database/schemas/postgresql.sql
    database/schemas/mysql.sql
    database/schemas/mariadb.sql
    installer/catalog.sh
    installer/compatibility_resolver.sh
    catalog/v2/schemas/runtime-definition.schema.json
    systemd/dsm-dashboard.service
)
for relative_path in "${REQUIRED_FILES[@]}"; do
    [[ -f "${PACKAGE_ROOT}/${relative_path}" ]] || fail "required release file missing: ${relative_path}"
done

FILE_COUNT=$(find "${PACKAGE_ROOT}" -type f | wc -l | tr -d ' ')
CREATED_AT=$("${PYTHON_BIN}" - "${SOURCE_DATE_EPOCH}" <<'PY'
import datetime
import sys
print(datetime.datetime.fromtimestamp(int(sys.argv[1]), datetime.timezone.utc).isoformat().replace("+00:00", "Z"))
PY
)

"${PYTHON_BIN}" - "${PACKAGE_ROOT}/release-manifest.json" "${VERSION}" "${COMMIT}" "${CREATED_AT}" "${ARCHIVE_NAME}" "${FILE_COUNT}" <<'PY'
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
        "version", "install.sh", "update.sh", "bin/dsm", "core/bootstrap.sh",
        "dashboard/server.py", "dashboard/server_part8.py", "database/manager.py",
        "database/runtime_backend.py", "database/operations.py",
        "database/schemas/sqlite.sql", "database/schemas/postgresql.sql",
        "database/schemas/mysql.sql", "database/schemas/mariadb.sql",
        "installer/catalog.sh", "installer/compatibility_resolver.sh",
        "catalog/v2/schemas/runtime-definition.schema.json", "systemd/dsm-dashboard.service"
    ],
}
pathlib.Path(target).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
PY
chmod 644 "${PACKAGE_ROOT}/release-manifest.json"

mkdir -p "${OUTPUT_DIR}"
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"
MANIFEST_PATH="${OUTPUT_DIR}/${MANIFEST_NAME}"
CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"
rm -f -- "${ARCHIVE_PATH}" "${MANIFEST_PATH}" "${CHECKSUM_PATH}"
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 --numeric-owner -cf - -C "${WORK_DIR}" "${PACKAGE_NAME}" | gzip -n >"${ARCHIVE_PATH}"
cp "${PACKAGE_ROOT}/release-manifest.json" "${MANIFEST_PATH}"
(
    cd "${OUTPUT_DIR}"
    sha256sum "${ARCHIVE_NAME}" >"${ARCHIVE_NAME}.sha256"
)

printf 'Release package: %s\n' "${ARCHIVE_PATH}"
printf 'Manifest: %s\n' "${MANIFEST_PATH}"
printf 'Checksum: %s\n' "${CHECKSUM_PATH}"
