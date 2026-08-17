#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$(uname -s)" == "Linux" ]] || { echo "Linux required" >&2; exit 77; }
[[ "${EUID}" -eq 0 ]] || { echo "root required" >&2; exit 77; }

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$(mktemp -d /tmp/capivara-install-smoke.XXXXXX)"

cleanup()
{
    if [[ -n "${SYSTEMD_SMOKE_UNIT:-}" ]]
    then
        systemctl stop "${SYSTEMD_SMOKE_UNIT}" 2>/dev/null || true
        systemctl reset-failed "${SYSTEMD_SMOKE_UNIT}" 2>/dev/null || true
    fi
    [[ "${TEST_ROOT}" == /tmp/capivara-install-smoke.* ]] \
        && rm -rf -- "${TEST_ROOT}"
}
trap cleanup EXIT

export DSM_ROOT="${TEST_ROOT}/dsm"
export DSM_LINK="${TEST_ROOT}/bin/dsm"
export SYSTEMD_DIR="${TEST_ROOT}/systemd"
export DSM_SERVICE_USER="root"
export DSM_SERVICE_GROUP="root"
export DSM_NODE_ROLE="controller"
export DSM_INSTALL_STEAMCMD="0"
export DSM_INSTALL_SYSTEMD="0"
export DSM_NON_INTERACTIVE="1"
export DSM_DATABASE_DRIVER="sqlite"
export DSM_DATABASE="${DSM_ROOT}/data/capivara.db"

bash "${SOURCE_ROOT}/install.sh" --local

[[ -x "${DSM_ROOT}/bin/dsm" ]]
[[ -L "${DSM_LINK}" ]]
[[ -f "${DSM_DATABASE}" ]]

python3 "${DSM_ROOT}/database/manager.py" \
    --root "${DSM_ROOT}" --driver sqlite --database "${DSM_DATABASE}" check \
    | python3 -c 'import json,sys; assert json.load(sys.stdin)["valid"]'

password_file="${TEST_ROOT}/admin-password"
printf 'Capivara-Smoke-Admin-2026!\n' >"${password_file}"
chmod 600 "${password_file}"

python3 "${DSM_ROOT}/database/registry.py" \
    --root "${DSM_ROOT}" bootstrap \
    --admin smoke.admin --admin-password-file "${password_file}" >/dev/null

python3 "${DSM_ROOT}/database/operations.py" \
    --root "${DSM_ROOT}" readiness \
    | python3 -c 'import json,sys; assert json.load(sys.stdin)["ready"]'

# Render every unit against the temporary root and validate it with systemd.
(
    # shellcheck source=../install.sh
    source "${SOURCE_ROOT}/install.sh"
    SYSTEMD_ACTIVE=1
    systemctl(){ :; }
    install_systemd_units >/dev/null
)
if command -v systemd-analyze >/dev/null 2>&1
then
    SYSTEMD_UNIT_PATH="${SYSTEMD_DIR}:/usr/lib/systemd/system:/lib/systemd/system" \
        systemd-analyze verify \
        "${SYSTEMD_DIR}"/*.service "${SYSTEMD_DIR}"/*.timer
fi

# Start the installed dashboard and exercise its unauthenticated health probe.
export DASHBOARD_HOST="127.0.0.1"
export DASHBOARD_PORT="18080"
systemctl show-environment >/dev/null 2>&1 \
    || { echo "active systemd is required for release smoke test" >&2; exit 1; }
SYSTEMD_SMOKE_UNIT="capivara-dashboard-smoke.service"
systemd-run \
    --unit="${SYSTEMD_SMOKE_UNIT}" \
    --property="WorkingDirectory=${DSM_ROOT}/dashboard" \
    --setenv="DSM_ROOT=${DSM_ROOT}" \
    --setenv="DSM_DATABASE_DRIVER=sqlite" \
    --setenv="DSM_DATABASE=${DSM_DATABASE}" \
    --setenv="DASHBOARD_HOST=${DASHBOARD_HOST}" \
    --setenv="DASHBOARD_PORT=${DASHBOARD_PORT}" \
    /usr/bin/python3 "${DSM_ROOT}/dashboard/server.py"
for _ in {1..30}
do
    if curl --fail --silent "http://127.0.0.1:18080/health" \
        | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "healthy"'
    then
        break
    fi
    sleep 1
done
systemctl is-active --quiet "${SYSTEMD_SMOKE_UNIT}"
curl --fail --silent "http://127.0.0.1:18080/health" \
    | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "healthy"'
systemctl stop "${SYSTEMD_SMOKE_UNIT}"
systemctl reset-failed "${SYSTEMD_SMOKE_UNIT}" 2>/dev/null || true
SYSTEMD_SMOKE_UNIT=""

# Reinstallation must preserve the initialized database and administrator.
bash "${SOURCE_ROOT}/install.sh" --local --reinstall
python3 "${DSM_ROOT}/database/operations.py" \
    --root "${DSM_ROOT}" readiness \
    | python3 -c 'import json,sys; assert json.load(sys.stdin)["ready"]'

echo "Linux installation smoke test passed."
