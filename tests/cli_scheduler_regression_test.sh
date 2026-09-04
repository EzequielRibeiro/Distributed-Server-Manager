#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="${ROOT}/install.sh"
CORE_INSTALLER="${ROOT}/install-core.sh"
CORE_ENGINE="${ROOT}/install-core-engine.sh"
UPDATER="${ROOT}/update.sh"
WORKER="${ROOT}/dashboard/workers/worker.sh"
SCHEDULER_UNIT="${ROOT}/systemd/dsm-scheduler.service"

fail(){ echo "FAIL: $*" >&2; exit 1; }

[[ ! -e "${SCHEDULER_UNIT}" ]] \
    || fail "retired standalone scheduler unit is still shipped"
grep -Fq 'start_worker scheduler_worker.sh' "${WORKER}" \
    || fail "consolidated Dashboard worker does not start scheduler_worker.sh"

if grep -Fq 'scheduler.sh daemon' "${WORKER}"
then
    fail "consolidated worker still references unsupported scheduler daemon action"
fi

grep -Fq 'install-core.sh' "${INSTALLER}" \
    || fail "installer wrapper does not delegate to install-core.sh"

# install-core.sh is now a compatibility entrypoint; the historical installer
# implementation lives in install-core-engine.sh and is sourced by it.
grep -Fq 'install-core-engine.sh' "${CORE_INSTALLER}" \
    || fail "installer compatibility entrypoint does not load its engine"
grep -Fq 'bin/cap' "${CORE_ENGINE}" \
    || fail "installer does not validate/install bin/cap"
grep -Fq '/usr/local/bin/cap' "${CORE_ENGINE}" \
    || fail "installer does not publish the global cap command"
grep -Fq 'bin/cap' "${UPDATER}" \
    || fail "updater does not validate/install bin/cap"
grep -Fq '/usr/local/bin/cap' "${UPDATER}" \
    || fail "updater does not publish the global cap command"

grep -Fq 'cap scheduler list|show|create|update|enable|disable|delete|run|status|check' "${ROOT}/bin/cap" \
    || fail "cap does not advertise scheduler management"
grep -Fq 'scheduler/cli.sh' "${ROOT}/bin/cap" \
    || fail "cap does not route scheduler management"

# `cap` sources bootstrap before handing legacy-compatible commands to
# bin/dsm-compat. The loaded marker must stay shell-local so the exec'd child
# performs its own bootstrap and gets functions such as config_show.
CONFIG_OUTPUT="$(bash -c 'source "$1/core/bootstrap.sh" >/dev/null; exec "$1/bin/dsm-compat" config show' _ "${ROOT}")"
grep -Fq 'DSM_DATABASE_DRIVER=' <<<"${CONFIG_OUTPUT}" \
    || fail "legacy CLI handoff did not reload bootstrap/config_show"

bash "${ROOT}/tests/scheduler_management_test.sh"
bash "${ROOT}/tests/update_handoff_test.sh"

echo "CLI, consolidated scheduler and updater handoff regression tests passed."
