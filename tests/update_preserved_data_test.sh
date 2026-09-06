#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "${ROOT}/update.sh"
trap - ERR
CASE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${CASE_ROOT}"' EXIT
INSTALL_DIR="${CASE_ROOT}/dsm"
STAGING_DIR="${CASE_ROOT}/stage"
BACKUP_DIR="${CASE_ROOT}/backups"
SYSTEMD_DIR="${CASE_ROOT}/systemd"
mkdir -p "${INSTALL_DIR}/config" "${STAGING_DIR}" "${SYSTEMD_DIR}"
echo old >"${INSTALL_DIR}/version"
echo config >"${INSTALL_DIR}/config/dsm.conf"
echo new >"${STAGING_DIR}/version"
declare -A INODES
for TREE in "${PRESERVED_TREES[@]}"; do
    mkdir -p "${INSTALL_DIR}/${TREE}"
    echo save >"${INSTALL_DIR}/${TREE}/save"
    INODES[${TREE}]="$(stat -c %i "${INSTALL_DIR}/${TREE}/save")"
done
validate_preserved_data
create_backup
for TREE in "${PRESERVED_TREES[@]}"; do
    if tar -tzf "${BACKUP_FILE}" | grep -F "dsm/${TREE}/"; then exit 1; fi
done
tar -xOf "${BACKUP_FILE}" dsm/config/dsm.conf | grep -q config
apply_update
for TREE in "${PRESERVED_TREES[@]}"; do
    [[ "$(stat -c %i "${INSTALL_DIR}/${TREE}/save")" == "${INODES[${TREE}]}" ]]
done
stop_services() { :; }
restart_services() { :; }
restore_database_backup() { echo restored >"${CASE_ROOT}/db-restored"; }
systemctl() { :; }
rollback
grep -q old "${INSTALL_DIR}/version"
[[ -f "${CASE_ROOT}/db-restored" ]]
for TREE in "${PRESERVED_TREES[@]}"; do
    [[ "$(stat -c %i "${INSTALL_DIR}/${TREE}/save")" == "${INODES[${TREE}]}" ]]
done
# A preflight rejection must not call rollback, even with a valid archive.
(
    UPDATE_FILES_STARTED=0
    UPDATE_TRANSACTION_STARTED=0
    rollback() { touch "${CASE_ROOT}/unexpected-rollback"; }
    collect_failure_diagnostics() { :; }
    update_failed preflight
) && exit 1
[[ ! -e "${CASE_ROOT}/unexpected-rollback" ]]
# Simulate a partial move / interrupted activation. Remaining trees in either
# location survive rollback, with identical inodes (no copy fallback).
mkdir -p "${INSTALL_DIR}.update-preserved"
mv "${INSTALL_DIR}/instances" "${INSTALL_DIR}.update-preserved/instances"
if validate_preserved_data; then exit 1; fi
rollback
for TREE in "${PRESERVED_TREES[@]}"; do
    [[ "$(stat -c %i "${INSTALL_DIR}/${TREE}/save")" == "${INODES[${TREE}]}" ]]
done
# Main rejects active games before taking any backup or stopping services.
set +e
(
    set -e
    for FN in require_root initialize_logging load_configuration validate_runtime_account validate_argument validate_package check_internet check_disk read_versions enforce_version_policy confirm_update; do
        eval "$FN() { :; }"
    done
    create_backup() { touch "${CASE_ROOT}/unexpected-backup"; }
    stop_services() { touch "${CASE_ROOT}/unexpected-stop"; }
    run_process_guard() { return 1; }
    UPDATE_FILES_STARTED=0; UPDATE_TRANSACTION_STARTED=0
    trap 'exit 77' ERR
    main --yes
)
RESULT=$?
set -e
[[ "${RESULT}" -eq 77 ]]
[[ ! -e "${CASE_ROOT}/unexpected-backup" && ! -e "${CASE_ROOT}/unexpected-stop" ]]
# A corrupt archive must leave all live game data and product files untouched.
GOOD_BACKUP="${BACKUP_FILE}"
BACKUP_FILE="${CASE_ROOT}/corrupt.tar.gz"
echo corrupt >"${BACKUP_FILE}"
if rollback; then exit 1; fi
for TREE in "${PRESERVED_TREES[@]}"; do
    [[ "$(stat -c %i "${INSTALL_DIR}/${TREE}/save")" == "${INODES[${TREE}]}" ]]
done
BACKUP_FILE="${GOOD_BACKUP}"
rmdir "${INSTALL_DIR}.update-restore"
# Conflicting recovery data must never be overwritten.
mkdir -p "${INSTALL_DIR}.update-preserved/instances"
echo retained >"${INSTALL_DIR}.update-preserved/instances/other"
if park_preserved_data; then exit 1; fi
grep -q retained "${INSTALL_DIR}.update-preserved/instances/other"
grep -q save "${INSTALL_DIR}/instances/save"
echo 'Update protected-data tests passed.'
