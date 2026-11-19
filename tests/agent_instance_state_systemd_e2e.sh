#!/usr/bin/env bash
# Isolated, disposable real-systemd proof of Agent traversal repair.
set -Eeuo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "Must run as root in isolated CI"; exit 1; }
[[ -d /run/systemd/system ]] || { echo "Real systemd unavailable"; exit 1; }
command -v runuser >/dev/null
command -v systemctl >/dev/null

UNIT="dsm-ci-permissions-1094.service"
GROUP="capivara-agent"
AGENT="capivara-agent"
GAME="dsm-ci-game-1094"
OUTSIDER="dsm-ci-other-1094"
INSTANCE="dsm-ci-permissions-1094"
ROOT="/var/lib/capivara-instances/${INSTANCE}"
WORKSHOP="${ROOT}/content/workshop"
UNIT_FILE="/run/systemd/system/${UNIT}"
INITIAL_PID=""

cleanup() {
  systemctl stop "${UNIT}" >/dev/null 2>&1 || true
  rm -f -- "${UNIT_FILE}"
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl reset-failed "${UNIT}" >/dev/null 2>&1 || true
  if [[ "${ROOT}" == "/var/lib/capivara-instances/dsm-ci-permissions-1094" ]]; then
    rm -rf -- "${ROOT}"
  fi
  userdel "${OUTSIDER}" >/dev/null 2>&1 || true
  userdel "${GAME}" >/dev/null 2>&1 || true
  userdel "${AGENT}" >/dev/null 2>&1 || true
  groupdel "${GROUP}" >/dev/null 2>&1 || true
}
# GitHub-hosted runners are disposable. Refuse to reuse or delete any identity
# which existed before this test.
for account in "${AGENT}" "${GAME}" "${OUTSIDER}"; do
  if getent passwd "${account}" >/dev/null; then
    echo "Pre-existing test account ${account}; refusing to modify"; exit 1
  fi
done
if getent group "${GROUP}" >/dev/null || [[ -e "${UNIT_FILE}" || -e "${ROOT}" ]]; then
  echo "Pre-existing test group, unit, or directory; refusing to modify"; exit 1
fi
trap cleanup EXIT

groupadd --system "${GROUP}"
useradd --system --no-create-home --gid "${GROUP}" "${AGENT}"
useradd --system --no-create-home --gid "${GROUP}" "${GAME}"
useradd --system --no-create-home "${OUTSIDER}"

install -d -o root -g root -m 0755 /var/lib/capivara-instances
cat >"${UNIT_FILE}" <<EOF
[Unit]
Description=Disposable Capivara instance permissions test
[Service]
Type=simple
User=${GAME}
StateDirectory=capivara-instances/${INSTANCE}
StateDirectoryMode=0700
ExecStart=/usr/bin/sleep 300
Restart=no
EOF
systemctl daemon-reload
systemctl start "${UNIT}"
systemctl is-active --quiet "${UNIT}"
INITIAL_PID="$(systemctl show --value -p MainPID "${UNIT}")"
[[ "${INITIAL_PID}" =~ ^[1-9][0-9]*$ ]]
[[ "$(stat -c %U:%G "${ROOT}")" == "${GAME}:${GROUP}" ]]
[[ "$(stat -c %a "${ROOT}")" == "700" ]]

install -d -o "${AGENT}" -g "${GROUP}" -m 0770 "${ROOT}/content"
install -d -o "${AGENT}" -g "${GROUP}" -m 0770 "${WORKSHOP}"

if runuser -u "${AGENT}" -- test -w "${WORKSHOP}"; then
  echo "Agent unexpectedly had access through 0700 root"; exit 1
fi

# This is the actual code shipped by the PR, not an inline chmod substitute.
PYTHONPATH="${GITHUB_WORKSPACE:-$PWD}/agents/linux/runtime" python3 - <<'PY'
from materializers.instance_state_access import reconcile_instance_root_traversal
spec = {
    "instance_id": "dsm-ci-permissions-1094",
    "user": "dsm-ci-game-1094",
}
assert reconcile_instance_root_traversal(spec) == "needs_group_traverse"
assert reconcile_instance_root_traversal(spec, apply=True) == "repaired"
assert reconcile_instance_root_traversal(spec, apply=True) == "already_accessible"
PY

[[ "$(stat -c %a "${ROOT}")" == "710" ]]
runuser -u "${AGENT}" -- test -w "${WORKSHOP}"
if runuser -u "${AGENT}" -- test -r "${ROOT}"; then
  echo "Agent unexpectedly gained root directory listing"; exit 1
fi
if runuser -u "${OUTSIDER}" -- test -x "${ROOT}"; then
  echo "Unrelated user unexpectedly gained root traversal"; exit 1
fi

# Simulate post-upgrade unit refresh WITHOUT stop/start of the running game.
sed -i 's/StateDirectoryMode=0700/StateDirectoryMode=0710/' "${UNIT_FILE}"
systemctl daemon-reload
[[ "${INITIAL_PID}" == "$(systemctl show --value -p MainPID "${UNIT}")" ]]
systemctl is-active --quiet "${UNIT}"
[[ "$(stat -c %a "${ROOT}")" == "710" ]]
echo "PASS: real systemd, Agent access, other-user isolation, preserved game PID"
