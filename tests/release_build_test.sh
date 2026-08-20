#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILDER="${ROOT}/release/build_release.sh"
TMP_DIR=$(mktemp -d)
cleanup(){ rm -rf -- "${TMP_DIR}"; }
trap cleanup EXIT
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }
resolve_python3(){
    local candidate
    for candidate in python3 python; do
        command -v "${candidate}" >/dev/null 2>&1 || continue
        if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1; then printf '%s\n' "${candidate}"; return 0; fi
    done
    fail "required Python 3 interpreter not found"
}
PYTHON_BIN="$(resolve_python3)"
bash -n "${BUILDER}"
"${BUILDER}" HEAD "${TMP_DIR}/first" >/dev/null
"${BUILDER}" HEAD "${TMP_DIR}/second" >/dev/null
VERSION=$(git -C "${ROOT}" show HEAD:version | tr -d '\r\n')
COMMIT=$(git -C "${ROOT}" rev-parse HEAD)
ARCHIVE_NAME="capivara-dsm-${VERSION}.tar.gz"
MANIFEST_NAME="capivara-dsm-${VERSION}.manifest.json"
(
    cd "${TMP_DIR}/first"
    sha256sum -c "${ARCHIVE_NAME}.sha256" >/dev/null
)
cmp -s "${TMP_DIR}/first/${ARCHIVE_NAME}" "${TMP_DIR}/second/${ARCHIVE_NAME}" || fail "two builds of the same commit are not reproducible"
mkdir -p "${TMP_DIR}/extract"
tar -xzf "${TMP_DIR}/first/${ARCHIVE_NAME}" -C "${TMP_DIR}/extract"
PACKAGE_ROOT="${TMP_DIR}/extract/capivara-dsm-${VERSION}"
for relative_path in \
    version install.sh update.sh bin/dsm core/bootstrap.sh \
    dashboard/server.py dashboard/server_part11.py dashboard/agent_remote_http.py \
    installer/catalog.sh installer/compatibility_resolver.sh \
    database/manager.py database/runtime_backend.py database/operations.py \
    agents/common/identity.py agents/linux/installer/install-agent.sh \
    agents/linux/runtime/agent.py agents/linux/services/capivara-agent.service \
    database/migrations/001_initial.sql \
    database/migrations_postgresql/001_initial.sql \
    database/migrations_mysql/001_initial.sql release-manifest.json
do
    [[ -f "${PACKAGE_ROOT}/${relative_path}" ]] || fail "required packaged file missing: ${relative_path}"
done
mapfile -t EXPECTED_MIGRATIONS < <(
    git -C "${ROOT}" ls-tree -r --name-only "${COMMIT}" -- database/migrations database/migrations_postgresql database/migrations_mysql \
        | grep -E '^database/migrations(_postgresql|_mysql)?/[0-9]{3}_[a-z0-9_]+\.sql$'
)
(( ${#EXPECTED_MIGRATIONS[@]} > 0 )) || fail "release commit contains no database migrations"
for relative_path in "${EXPECTED_MIGRATIONS[@]}"; do [[ -f "${PACKAGE_ROOT}/${relative_path}" ]] || fail "packaged database migration missing: ${relative_path}"; done
mapfile -t PACKAGED_MIGRATIONS < <(
    for directory in migrations migrations_postgresql migrations_mysql; do find "${PACKAGE_ROOT}/database/${directory}" -maxdepth 1 -type f -name '*.sql' -printf "database/${directory}/%f\n"; done | sort
)
mapfile -t EXPECTED_MIGRATIONS_SORTED < <(printf '%s\n' "${EXPECTED_MIGRATIONS[@]}" | sort)
[[ "$(printf '%s\n' "${PACKAGED_MIGRATIONS[@]}")" == "$(printf '%s\n' "${EXPECTED_MIGRATIONS_SORTED[@]}")" ]] || fail "packaged database migration set differs from release commit"
for forbidden_path in .git .idea .artifacts cache logs packages instances tools/steamcmd runtime/state dashboard/state/dashboard_state.json; do [[ ! -e "${PACKAGE_ROOT}/${forbidden_path}" ]] || fail "generated or machine-local path was packaged: ${forbidden_path}"; done
"${PYTHON_BIN}" - "${TMP_DIR}/first/${MANIFEST_NAME}" "${PACKAGE_ROOT}/release-manifest.json" "${VERSION}" "${COMMIT}" <<'PY'
import json,pathlib,sys
external_path, internal_path, expected_version, expected_commit = sys.argv[1:]
external=pathlib.Path(external_path).read_bytes(); internal=pathlib.Path(internal_path).read_bytes()
if external != internal: raise SystemExit("external and packaged manifests differ")
manifest=json.loads(internal)
if manifest["version"] != expected_version: raise SystemExit("manifest version mismatch")
if manifest["git_commit"] != expected_commit: raise SystemExit("manifest commit mismatch")
if manifest["kind"] != "CapivaraReleaseManifest": raise SystemExit("manifest kind mismatch")
PY
printf 'Release build tests passed.\n'
