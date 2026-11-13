#!/usr/bin/env bash
# Sandbox-only rehearsal of ACTUAL update.sh functions. Never invoke its main().
set -Eeuo pipefail
[[ $# -eq 3 ]] || { echo "usage: fixture ROOT UPDATE_SCRIPT prepare|apply|rollback" >&2; exit 2; }
ROOT="$1"; UPDATE_SCRIPT="$2"; MODE="$3"
[[ "$MODE" =~ ^(prepare|apply|rollback)$ ]] || exit 2
[[ ! -L "$ROOT" && -d "$ROOT" ]] || { echo "invalid disposable workspace" >&2; exit 2; }
ROOT="$(realpath -e -- "$ROOT")"
case "$ROOT" in
    /tmp/*|/var/tmp/*) ;;
    *) echo "outside disposable tmp" >&2;exit 2;;
esac
# The only updater script allowed is the exact checked-out source file.
[[ -f "$UPDATE_SCRIPT" && ! -L "$UPDATE_SCRIPT" && "$(basename -- "$UPDATE_SCRIPT")" == "update.sh" ]] || exit 2
[[ "$ROOT" != /opt/dsm* && "$ROOT" != /srv/capivara-data* ]] || exit 2
[[ -f "$ROOT/fixture-owner" && "$(cat -- "$ROOT/fixture-owner")" == "DSM928_DISPOSABLE_FIXTURE_V1" ]] || exit 2
source "$UPDATE_SCRIPT"  # source guard: does NOT invoke main()/traps

# Overrides must precede each actual updater operation; no production paths.
INSTALL_DIR="$ROOT/installed"
STAGING_DIR="$ROOT/staging"
NEW_SRC="$ROOT/new-payload"
BACKUP_DIR="$ROOT/backups"
SYSTEMD_DIR="$ROOT/fake-systemd"
CONFIG_FILE="$INSTALL_DIR/config/dsm.conf"
CAP_LINK="$ROOT/cap-sandbox-link"
DSM_USER=""
DSM_GROUP=""
SYSTEMD_ENABLED=0
NO_BACKUP=0
UPDATE_TRANSACTION_STARTED=1
mkdir -p "$SYSTEMD_DIR" "$BACKUP_DIR"

# Guard all callbacks of the real rollback that would otherwise touch systemd
# or a live database. File/data preservation functions remain unchanged.
systemctl() {
    if [[ "$1" == "daemon-reload" ]]; then return 0;fi
    echo "unexpected systemctl command in fixture" >&2
    return 95
}
stop_services() { :; }
restart_services() { :; }
restart_game_instances() { :; }
restore_database_backup() { :; }

[[ "$INSTALL_DIR" == "$ROOT/installed" && "$BACKUP_DIR" == "$ROOT/backups" ]] || exit 2
[[ ! -L "$INSTALL_DIR" && -d "$INSTALL_DIR" ]] || exit 2
case "$MODE" in
    prepare)
        validate_preserved_data
        create_backup
        [[ -s "$BACKUP_FILE" ]]
        ;;
    apply)
        validate_preserved_data
        create_staging
        preserve_data
        validate_staging
        apply_update
        [[ "$(cat -- "$INSTALL_DIR/version")" == "2.0.999-fixture" ]]
        ;;
    rollback)
        mapfile -d '' -t backups < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'dsm-before-update-*.tar.gz' -print0)
        [[ "${#backups[@]}" -eq 1 ]] || { echo "missing or ambiguous snapshot" >&2; exit 2; }
        BACKUP_FILE="${backups[0]}"
        rollback
        [[ "$(cat -- "$INSTALL_DIR/version")" == "2.0.998-fixture" ]]
        ;;
esac
