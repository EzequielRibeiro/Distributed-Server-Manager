#!/usr/bin/env bash
# Disposable real-systemd test of protected backup create with a private 0710 root.
set -Eeuo pipefail
[[ "$EUID" -eq 0 ]] || { echo "Requires root in disposable CI"; exit 1; }
[[ -d /run/systemd/system ]] || { echo "Real systemd unavailable"; exit 1; }
[[ -n "$GITHUB_WORKSPACE" ]] || { echo "Requires GitHub Actions workspace"; exit 1; }

GROUP="capivara-agent"
AGENT="capivara-agent"
OWNER="capivara-instance"
INSTANCE_ID="dsm-ci-backup-1102"
INSTANCE="/var/lib/capivara-instances/$INSTANCE_ID"
STATE="/var/lib/capivara-agent-ci-backup-1102"
UNIT="/run/systemd/system/capivara-agent-backup-create@.service"
GAME_UNIT="/run/systemd/system/capivara-instance-$INSTANCE_ID.service"
POLICY="/etc/polkit-1/rules.d/49-capivara-agent-instance-units.rules"

# Never reuse existing users or files. The GitHub-hosted runner is disposable.
for user in "$AGENT" "$OWNER"; do
  ! getent passwd "$user" >/dev/null || { echo "Existing identity: $user"; exit 1; }
done
! getent group "$GROUP" >/dev/null || { echo "Existing group"; exit 1; }
for entry in "$INSTANCE" "$STATE" "$UNIT" "$GAME_UNIT" "$POLICY"; do
  [[ ! -e "$entry" && ! -L "$entry" ]] || { echo "Existing path: $entry"; exit 1; }
done
cleanup() {
  systemctl stop "$(basename "$GAME_UNIT")" >/dev/null 2>&1 || true
  rm -f -- "$UNIT" "$GAME_UNIT" "$POLICY"
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl reset-failed "capivara-agent-backup-create@dsm-ci-create-1102.service" >/dev/null 2>&1 || true
  systemctl reset-failed "$(basename "$GAME_UNIT")" >/dev/null 2>&1 || true
  [[ "$INSTANCE" == "/var/lib/capivara-instances/dsm-ci-backup-1102" ]] && rm -rf -- "$INSTANCE"
  [[ "$STATE" == "/var/lib/capivara-agent-ci-backup-1102" ]] && rm -rf -- "$STATE"
  userdel "$OWNER" >/dev/null 2>&1 || true
  userdel "$AGENT" >/dev/null 2>&1 || true
  groupdel "$GROUP" >/dev/null 2>&1 || true
}
trap cleanup EXIT

groupadd --system "$GROUP"
useradd --system --no-create-home --gid "$GROUP" "$AGENT"
useradd --system --no-create-home --gid "$GROUP" "$OWNER"
if [[ ! -d /var/lib/capivara-instances ]]; then
  install -d -o root -g root -m 0711 /var/lib/capivara-instances
fi
install -d -o "$OWNER" -g "$GROUP" -m 0710 "$INSTANCE"
install -d -o "$OWNER" -g "$GROUP" -m 0700 "$INSTANCE/config"
printf 'hostname = "Disposable private DayZ test";\n' > "$INSTANCE/config/serverDZ.cfg"
chown "$OWNER:$GROUP" "$INSTANCE/config/serverDZ.cfg"
chmod 0600 "$INSTANCE/config/serverDZ.cfg"

install -d -o "$AGENT" -g "$GROUP" -m 0700 \
  "$STATE" "$STATE/instances" "$STATE/backups" \
  "$STATE/backup-create-locks" "$STATE/privileged-backup-create" \
  "$STATE/backup-results"
printf '{"agent_id":"ci-agent-1102"}\n' > "$STATE/agent.json"
cat > "$STATE/instances/$INSTANCE_ID.json" <<JSON
{
  "instance_id": "$INSTANCE_ID",
  "agent_id": "ci-agent-1102",
  "game_id": "dayz",
  "runtime_id": "dayz.stable",
  "files_root": "$INSTANCE",
  "instance_state_root": "$INSTANCE",
  "storage_limit_bytes": 67108864
}
JSON
chown "$AGENT:$GROUP" "$STATE/agent.json" "$STATE/instances/$INSTANCE_ID.json"
chmod 0600 "$STATE/agent.json" "$STATE/instances/$INSTANCE_ID.json"

# Exercise PR production template and policy, with only the CI code and state
# paths substituted.  Protected instance tree remains read-only to the unit.
sed \
  -e "s|/opt/capivara-agent|$GITHUB_WORKSPACE/agents/linux|g" \
  -e "s|/var/lib/capivara-agent|$STATE|g" \
  -e "s|/etc/capivara-agent/agent.json|$STATE/agent.json|g" \
  "$GITHUB_WORKSPACE/agents/linux/services/capivara-agent-backup-create@.service" > "$UNIT"
install -m 0644 "$GITHUB_WORKSPACE/agents/linux/policy/49-capivara-agent-instance-units.rules" "$POLICY"
cat > "$GAME_UNIT" <<EOF
[Unit]
Description=Disposable running game for backup permissions test
[Service]
Type=simple
User=$OWNER
Group=$GROUP
ExecStart=/usr/bin/sleep 300
Restart=no
EOF
systemctl daemon-reload
systemctl start "$(basename "$GAME_UNIT")"
systemctl is-active --quiet "$(basename "$GAME_UNIT")"
INITIAL_PID="$(systemctl show --value -p MainPID "$(basename "$GAME_UNIT")")"
[[ "$INITIAL_PID" =~ ^[1-9][0-9]*$ ]]

[[ "$(stat -c %a "$INSTANCE")" == 710 ]]
if runuser -u "$AGENT" -- test -r "$INSTANCE/config/serverDZ.cfg"; then
  echo "FAIL: Agent can read private server files without helper"; exit 1
fi
if runuser -u "$AGENT" -- ls -A "$INSTANCE" >/dev/null 2>&1; then
  echo "FAIL: Agent can enumerate 0710 root"; exit 1
fi

# The unprivileged Agent dispatches into the real root-owned systemd unit,
# then verifies the archive and reads a restored copy in a temp directory.
runuser -u "$AGENT" -- env \
  CAPIVARA_AGENT_STATE_DIR="$STATE" \
  PYTHONPATH="$GITHUB_WORKSPACE/agents/linux/runtime" \
  CAPIVARA_BACKUP_CREATE_UNIT_TEMPLATE='capivara-agent-backup-create@{command_id}.service' \
  python3 - <<'PY'
import hashlib
import os
import tempfile
from pathlib import Path
import backup_client

command = {
    "command_id": "dsm-ci-create-1102",
    "instance_id": "dsm-ci-backup-1102",
    "action": "create",
    "reason": "manual",
    "policy": {"mode": "full", "compression": "gzip",
               "consistency": "live", "storage_limit_bytes": 67108864},
}
reports = backup_client.apply_backup_commands({"agent_id": "ci-agent-1102"}, [command])
assert len(reports) == 1, reports
report = reports[0]
assert report["status"] == "completed", report
archive = Path(report["artifact_path"])
assert archive.is_file() and archive.stat().st_size > 430
assert archive.parent.name == "dsm-ci-backup-1102"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == report["sha256"]
assert archive.stat().st_uid == os.geteuid()
with tempfile.TemporaryDirectory() as directory:
    stage = Path(directory)
    backup_client._safe_extract(archive, stage)
    cfg = stage / "config" / "serverDZ.cfg"
    assert cfg.read_text() == 'hostname = "Disposable private DayZ test";\n'
print("PASS: protected archive creation and isolated restore")
PY
[[ "$INITIAL_PID" == "$(systemctl show --value -p MainPID "$(basename "$GAME_UNIT")")" ]]
systemctl is-active --quiet "$(basename "$GAME_UNIT")"
[[ "$(stat -c %a "$INSTANCE")" == 710 ]]
echo "PASS: real systemd helper, full archive, game PID preserved, 0710 intact"
