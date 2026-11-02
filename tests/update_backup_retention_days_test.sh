#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT}/update.sh"
# Fail with an actionable assertion, also on runners without PostgreSQL tools.
trap 'result=$?; printf "Retention regression failed at line %s (exit %s): %s\n" "${LINENO}" "${result}" "${BASH_COMMAND}" >&2' ERR
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT
BACKUP_DIR="${TMP}/backups"
DSM_DATABASE_DRIVER=postgresql
UPDATE_BACKUP_RETENTION_DAYS=14
# Synthetic custom-format fixtures are accepted by a test-only pg_restore stub.
pg_restore() { [[ "$1" == "--list" && "$(head -c 5 -- "$2")" == "PGDMP" ]]; }
mkdir -p "${BACKUP_DIR}" "${TMP}/payload"
printf "backup fixture\n" >"${TMP}/payload/content"
make_backup() {
    local stamp="$1"; local kind="${2:-valid}"
    local stem="${BACKUP_DIR}/dsm-before-update-${stamp}"
    if [[ "${kind}" == corrupt ]]; then
        printf 'bad archive' >"${stem}.tar.gz"
    else
        tar -czf "${stem}.tar.gz" -C "${TMP}" payload
    fi
    if [[ "${kind}" != unpaired ]]; then
        printf 'PGDMPmock database dump' >"${stem}.database.dump"
    fi
}
recent="$(date -d '1 day ago' +%Y%m%d-%H%M%S)"
old="$(date -d '20 days ago' +%Y%m%d-%H%M%S)"
older="$(date -d '30 days ago' +%Y%m%d-%H%M%S)"
corrupt="$(date -d '21 days ago' +%Y%m%d-%H%M%S)"
unpaired="$(date -d '22 days ago' +%Y%m%d-%H%M%S)"
make_backup "${old}"
make_backup "${older}"
make_backup "${corrupt}" corrupt
make_backup "${unpaired}" unpaired
for offset in {1..16}; do
    stamp="$(date -d "${offset} hours ago" +%Y%m%d-%H%M%S)"
    make_backup "${stamp}"
done
prune_update_backups >/dev/null
[[ "$(find "${BACKUP_DIR}" -type f -name 'dsm-before-update-*.tar.gz' | wc -l)" -eq 18 ]] || {
    echo 'FAIL: expected 16 recent + corrupt + incomplete archives'; exit 1;
}
[[ ! -f "${BACKUP_DIR}/dsm-before-update-${old}.tar.gz" ]]
[[ ! -f "${BACKUP_DIR}/dsm-before-update-${older}.database.dump" ]]
[[ -f "${BACKUP_DIR}/dsm-before-update-${corrupt}.tar.gz" ]]
[[ -f "${BACKUP_DIR}/dsm-before-update-${unpaired}.tar.gz" ]]
# Fall back to latest valid past the window; invalid newer ones cannot win.
for offset in {1..16}; do
    stamp="$(date -d "${offset} hours ago" +%Y%m%d-%H%M%S)"
    rm -f -- "${BACKUP_DIR}/dsm-before-update-${stamp}.tar.gz" \
        "${BACKUP_DIR}/dsm-before-update-${stamp}.database.dump"
done
make_backup "${old}"
make_backup "${older}"
prune_update_backups >/dev/null
[[ -f "${BACKUP_DIR}/dsm-before-update-${old}.tar.gz" ]]
[[ -f "${BACKUP_DIR}/dsm-before-update-${corrupt}.tar.gz" ]]
[[ -f "${BACKUP_DIR}/dsm-before-update-${unpaired}.tar.gz" ]]
[[ ! -f "${BACKUP_DIR}/dsm-before-update-${older}.tar.gz" ]]
# Do not prune when no valid backup exists.
rm -f -- "${BACKUP_DIR}/dsm-before-update-${old}.tar.gz" "${BACKUP_DIR}/dsm-before-update-${old}.database.dump"
prune_update_backups >/dev/null
[[ -f "${BACKUP_DIR}/dsm-before-update-${corrupt}.tar.gz" ]]
[[ -f "${BACKUP_DIR}/dsm-before-update-${unpaired}.tar.gz" ]]
echo 'PASS: 14-day unlimited retention, last-valid fallback, fail-closed corrupt/incomplete backups'
