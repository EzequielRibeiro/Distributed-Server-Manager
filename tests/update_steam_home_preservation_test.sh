#!/usr/bin/env bash
# Regression: upgrade and rollback must not delete the SteamCMD authenticated HOME.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT}/update.sh"
trap - ERR
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT
INSTALL_DIR="${TMP}/dsm"
STAGING_DIR="${TMP}/staging"
BACKUP_DIR="${TMP}/backups"
SYSTEMD_DIR="${TMP}/systemd"
mkdir -p "${INSTALL_DIR}/.local/share/Steam/config" "${INSTALL_DIR}/.steam" \
    "${INSTALL_DIR}/config" "${STAGING_DIR}" "${BACKUP_DIR}" "${SYSTEMD_DIR}"
printf 'old\n' >"${INSTALL_DIR}/version"
printf 'new\n' >"${STAGING_DIR}/version"
printf 'test-config\n' >"${INSTALL_DIR}/config/dsm.conf"
printf 'session-state-fixture\n' >"${INSTALL_DIR}/.local/share/Steam/config/config.vdf"
chmod 600 "${INSTALL_DIR}/.local/share/Steam/config/config.vdf"
ln -s "${INSTALL_DIR}/.local/share/Steam" "${INSTALL_DIR}/.steam/steam"
ln -s "${INSTALL_DIR}/.local/share/Steam" "${INSTALL_DIR}/.steam/root"
BEFORE="$(sha256sum "${INSTALL_DIR}/.local/share/Steam/config/config.vdf" | awk '{print $1}')"
# A pre-update snapshot must contain the authentication state for recovery.
create_backup >/dev/null
[[ "$(stat -c %a "${BACKUP_FILE}")" == 600 ]]
tar -xOf "${BACKUP_FILE}" dsm/.local/share/Steam/config/config.vdf | grep -q session-state-fixture
preserve_data >/dev/null
apply_update >/dev/null
AFTER="$(sha256sum "${INSTALL_DIR}/.local/share/Steam/config/config.vdf" | awk '{print $1}')"
[[ "${BEFORE}" == "${AFTER}" ]]
[[ "$(stat -c %a "${INSTALL_DIR}/.local/share/Steam/config/config.vdf")" == 600 ]]
[[ -L "${INSTALL_DIR}/.steam/steam" && -L "${INSTALL_DIR}/.steam/root" ]]
[[ -f "${INSTALL_DIR}/.steam/steam/config/config.vdf" ]]
# Restore the original release and its backed-up session state.
stop_services(){ :; }
restart_services(){ :; }
restore_database_backup(){ :; }
systemctl(){ :; }
rollback >/dev/null
[[ "$(sha256sum "${INSTALL_DIR}/.local/share/Steam/config/config.vdf" | awk '{print $1}')" == "${BEFORE}" ]]
[[ -L "${INSTALL_DIR}/.steam/steam" ]]
[[ "$(cat "${INSTALL_DIR}/version")" == old ]]
echo 'PASS: DSM updater preserves Steam HOME and restores it on rollback'
