#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="${ROOT}/install.sh"
CORE_INSTALLER="${ROOT}/install-core.sh"
UPDATER="${ROOT}/update.sh"
SCHEDULER_UNIT="${ROOT}/systemd/dsm-scheduler.service"

fail(){ echo "FAIL: $*" >&2; exit 1; }

# Scheduler must invoke the public long-running entry point actually exposed by
# scheduler/scheduler.sh. The historical 'daemon' argument caused an endless
# systemd restart loop on installed nodes.
grep -Fq 'ExecStart=/bin/bash /opt/dsm/scheduler/scheduler.sh run' \
    "${SCHEDULER_UNIT}" \
    || fail "scheduler unit does not use scheduler.sh run"

if grep -Fq 'scheduler.sh daemon' "${SCHEDULER_UNIT}"
then
    fail "scheduler unit still references unsupported daemon action"
fi

# install.sh is now the interactive/bootstrap wrapper. The installation and
# validation contract for public CLIs lives in install-core.sh.
grep -Fq 'install-core.sh' "${INSTALLER}" \
    || fail "installer wrapper does not delegate to install-core.sh"

# `cap` is the public CLI. `dsm` remains only as a compatibility command, but
# both entry points must stay installable while compatibility is supported.
grep -Fq 'bin/cap' "${CORE_INSTALLER}" \
    || fail "installer does not validate/install bin/cap"
grep -Fq '/usr/local/bin/cap' "${CORE_INSTALLER}" \
    || fail "installer does not publish the global cap command"
grep -Fq 'bin/cap' "${UPDATER}" \
    || fail "updater does not validate/install bin/cap"
grep -Fq '/usr/local/bin/cap' "${UPDATER}" \
    || fail "updater does not publish the global cap command"

# A validated release must execute its own updater, not the updater from the
# currently installed version. This is what makes new post-install rules take
# effect during the transition that introduces them.
bash "${ROOT}/tests/update_handoff_test.sh"

echo "CLI, scheduler and updater handoff regression tests passed."
