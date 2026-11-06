#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(mktemp -d /tmp/dsm-pr988-cloned-update.XXXXXX)
trap 'rm -rf -- "$ROOT"' EXIT
TARGET="$(cd "$(dirname "$0")/.." && pwd)"
# Only clone the candidate release files, never the installed /opt/dsm tree.
# The existing game instances and production data are never accessed.
mkdir -p "$ROOT/installed" "$ROOT/stage" "$ROOT/backups" "$ROOT/systemd"
rsync -a --exclude='.git' --exclude='dist' "$TARGET/" "$ROOT/installed/"
printf '2.0.132-rc.4\n' >"$ROOT/installed/version"
printf 'pre-upgrade-marker\n' >"$ROOT/installed/rc4-product.marker"
for TREE in instances game-data runtime/hybrid-agent-state runtime/hybrid-instance-storage; do
 mkdir -p "$ROOT/installed/$TREE"
 printf 'original-data-for-%s\n' "$TREE" >"$ROOT/installed/$TREE/verify.marker"
done
declare -A OLD_INODE OLD_HASH
for TREE in instances game-data runtime/hybrid-agent-state runtime/hybrid-instance-storage; do
 OLD_INODE["$TREE"]=$(stat -c %i "$ROOT/installed/$TREE/verify.marker")
 OLD_HASH["$TREE"]=$(sha256sum "$ROOT/installed/$TREE/verify.marker" | cut -d' ' -f1)
done
source "$TARGET/update.sh"
trap - ERR
INSTALL_DIR="$ROOT/installed"
STAGING_DIR="$ROOT/stage"
BACKUP_DIR="$ROOT/backups"
SYSTEMD_DIR="$ROOT/systemd"
NEW_SRC="$TARGET"
OLD_VERSION="2.0.132-rc.4"
NEW_VERSION="2.0.132"
DSM_USER=""
DSM_GROUP=""
DSM_DATABASE_DRIVER="sqlite"
ACTIVE_GAME_UNITS=()
DISCOVERED_SERVICES=()
RESTORE_SERVICES=()
STOP_SERVICES=()
systemctl() { :; }
stop_services() { :; }
restart_services() { :; }
stop_game_instances() { :; }
restart_game_instances() { :; }
restore_database_backup() { :; }
validate_preserved_data
enforce_version_policy
create_backup
create_staging
preserve_data
validate_staging
apply_update
update_version_file
test "$(cat "$INSTALL_DIR/version")" = "2.0.132"
test ! -f "$INSTALL_DIR/rc4-product.marker"
for TREE in instances game-data runtime/hybrid-agent-state runtime/hybrid-instance-storage; do
 test "$(stat -c %i "$INSTALL_DIR/$TREE/verify.marker")" = "${OLD_INODE[$TREE]}"
 test "$(sha256sum "$INSTALL_DIR/$TREE/verify.marker" | cut -d' ' -f1)" = "${OLD_HASH[$TREE]}"
done
echo 'CLONED_UPDATE_PASS=yes version=2.0.132'
rollback
test "$(cat "$INSTALL_DIR/version")" = "2.0.132-rc.4"
test -f "$INSTALL_DIR/rc4-product.marker"
for TREE in instances game-data runtime/hybrid-agent-state runtime/hybrid-instance-storage; do
 test "$(stat -c %i "$INSTALL_DIR/$TREE/verify.marker")" = "${OLD_INODE[$TREE]}"
 test "$(sha256sum "$INSTALL_DIR/$TREE/verify.marker" | cut -d' ' -f1)" = "${OLD_HASH[$TREE]}"
done
echo 'CLONED_ROLLBACK_PASS=yes version=2.0.132-rc.4'
test -f "$BACKUP_FILE"
gzip -t "$BACKUP_FILE"
echo 'BACKUP_CLONE_CRC=OK'
echo 'PROTECTED_INODE_HASH_UNCHANGED=yes'
