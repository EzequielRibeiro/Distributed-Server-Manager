#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="${ROOT}/install.sh"
CORE_INSTALLER="${ROOT}/install-core.sh"
UPDATER="${ROOT}/update.sh"
SCHEDULER_UNIT="${ROOT}/systemd/dsm-scheduler.service"

fail(){ echo "FAIL: $*" >&2; exit 1; }

grep -Fq 'ExecStart=/bin/bash /opt/dsm/scheduler/scheduler.sh run' \
    "${SCHEDULER_UNIT}" \
    || fail "scheduler unit does not use scheduler.sh run"

if grep -Fq 'scheduler.sh daemon' "${SCHEDULER_UNIT}"
then
    fail "scheduler unit still references unsupported daemon action"
fi

grep -Fq 'install-core.sh' "${INSTALLER}" \
    || fail "installer wrapper does not delegate to install-core.sh"

grep -Fq 'bin/cap' "${CORE_INSTALLER}" \
    || fail "installer does not validate/install bin/cap"
grep -Fq '/usr/local/bin/cap' "${CORE_INSTALLER}" \
    || fail "installer does not publish the global cap command"
grep -Fq 'bin/cap' "${UPDATER}" \
    || fail "updater does not validate/install bin/cap"
grep -Fq '/usr/local/bin/cap' "${UPDATER}" \
    || fail "updater does not publish the global cap command"

grep -Fq 'cap scheduler list|show|create|update|enable|disable|delete|run|status|check' "${ROOT}/bin/cap" \
    || fail "cap does not advertise scheduler management"
grep -Fq 'scheduler/cli.sh' "${ROOT}/bin/cap" \
    || fail "cap does not route scheduler management"

bash "${ROOT}/tests/scheduler_management_test.sh"
bash "${ROOT}/tests/update_handoff_test.sh"

echo "CLI, scheduler and updater handoff regression tests passed."
