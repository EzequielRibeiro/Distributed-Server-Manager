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

# install-core.sh is the public wrapper; the implementation lives in
# install-core-engine.sh and is sourced by it.
grep -Fq 'install-core-engine.sh' "${CORE_INSTALLER}" \
    || fail "installer wrapper does not load its engine"
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

# The canonical cap CLI must bootstrap its own shell context before dispatching
# config commands. CAPIVARA_NODE_ROLE is the explicit read-only resolver override
# and is intentionally not replaced by config/dsm.conf during bootstrap.
CONFIG_OUTPUT="$(CAPIVARA_NODE_ROLE=controller "${ROOT}/bin/cap" config show)"
grep -Fq 'DSM_DATABASE_DRIVER=' <<<"${CONFIG_OUTPUT}" \
    || fail "canonical cap config handoff did not load bootstrap/config_show"

# automation_cli.py is launched directly from database/. Its dependency graph
# imports top-level core modules, so --help must work without any ambient
# PYTHONPATH from a development checkout or systemd service.
env -u PYTHONPATH python3 "${ROOT}/database/automation_cli.py" --help >/dev/null \
    || fail "automation CLI cannot resolve repository-root Python modules"

bash "${ROOT}/tests/scheduler_management_test.sh"
bash "${ROOT}/tests/update_handoff_test.sh"

echo "CLI, consolidated scheduler and updater handoff regression tests passed."
