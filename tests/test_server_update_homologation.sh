#!/usr/bin/env bash
set -Eeuo pipefail

# Destructive integration test for a dedicated DSM test server.
# It exercises the installed systemd manager and the official package updater.

[[ "$(uname -s)" == "Linux" ]] || { echo "Linux required" >&2; exit 77; }
[[ "${EUID}" -eq 0 ]] || { echo "root required" >&2; exit 77; }
[[ "${DSM_HOMOLOGATION_CONFIRM:-}" == "dedicated-test-server" ]] || {
    echo "Refusing to run without DSM_HOMOLOGATION_CONFIRM=dedicated-test-server" >&2
    exit 2
}

PACKAGE_ROOT="${1:-}"
[[ -d "${PACKAGE_ROOT}" ]] || { echo "Usage: $0 /path/to/extracted-release" >&2; exit 2; }
PACKAGE_ROOT="$(realpath "${PACKAGE_ROOT}")"
[[ -x "${PACKAGE_ROOT}/update.sh" || -f "${PACKAGE_ROOT}/update.sh" ]] \
    || { echo "Package update.sh not found" >&2; exit 2; }
[[ -s "${PACKAGE_ROOT}/version" ]] || { echo "Package version not found" >&2; exit 2; }
[[ -s /opt/dsm/version ]] || { echo "DSM is not installed in /opt/dsm" >&2; exit 2; }
[[ -r /opt/dsm/config/dsm.conf ]] || { echo "DSM configuration not found" >&2; exit 2; }
command -v systemctl >/dev/null
systemctl show-environment >/dev/null 2>&1 \
    || { echo "An active systemd manager is required" >&2; exit 77; }

TEST_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
EVIDENCE_ROOT="${DSM_HOMOLOGATION_EVIDENCE_ROOT:-/var/tmp/dsm-update-homologation}"
EVIDENCE_DIR="${EVIDENCE_ROOT}/${TEST_ID}"
RUNTIME_DIR="/var/tmp/dsm-update-homologation-runtime-${TEST_ID}"
UNIT_DIR="/etc/systemd/system"
UNIT_PREFIX="dsm-homologation-${TEST_ID}"
RESULT_FILE="${EVIDENCE_DIR}/result.env"
UPDATE_LOG="${EVIDENCE_DIR}/successful-update.log"
ROLLBACK_LOG="${EVIDENCE_DIR}/rollback-update.log"
DIAGNOSTICS_BEFORE=""
CONFIG_BEFORE=""
VERSION_BEFORE="$(tr -d '\r\n' </opt/dsm/version)"
PACKAGE_VERSION="$(tr -d '\r\n' <"${PACKAGE_ROOT}/version")"
SUCCESS_UPDATE_DONE=0
ROLLBACK_TEST_DONE=0

set -a
# shellcheck source=/dev/null
source /opt/dsm/config/dsm.conf
set +a

mkdir -p "${EVIDENCE_DIR}" "${RUNTIME_DIR}"
chmod 700 "${EVIDENCE_DIR}" "${RUNTIME_DIR}"

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    printf 'status=failed\nreason=%q\n' "$*" >"${RESULT_FILE}"
    exit 1
}

unit_name() { printf '%s-%s.service\n' "${UNIT_PREFIX}" "$1"; }

capture_host_state() {
    local label="$1"
    {
        date --iso-8601=seconds
        uname -a
        cat /etc/os-release
        printf 'installed_version=%s\npackage_version=%s\n' "${VERSION_BEFORE}" "${PACKAGE_VERSION}"
        systemctl --version
        df -h /opt /var/tmp
        systemctl list-unit-files 'dsm-*.service' --no-pager
        systemctl list-units 'dsm-*.service' --all --no-pager
    } >"${EVIDENCE_DIR}/${label}-host-state.txt" 2>&1
}

capture_dsm_health() {
    local label="$1"
    local dashboard_port="8080"
    /opt/dsm/bin/cap --help >"${EVIDENCE_DIR}/${label}-cap-help.txt" 2>&1
    python3 /opt/dsm/database/manager.py --root /opt/dsm check \
        >"${EVIDENCE_DIR}/${label}-database.json" 2>&1
    if systemctl is-active --quiet dsm-dashboard.service
    then
        if [[ -r /opt/dsm/dashboard/config/dashboard.conf ]]
        then
            dashboard_port="$(awk -F= '$1 == "PORT" {gsub(/[^0-9]/, "", $2); print $2; exit}' \
                /opt/dsm/dashboard/config/dashboard.conf)"
            dashboard_port="${dashboard_port:-8080}"
        fi
        curl --fail --silent --show-error --max-time 10 \
            "http://127.0.0.1:${dashboard_port}/health" \
            >"${EVIDENCE_DIR}/${label}-dashboard-health.json"
    fi
}

write_runner() {
    cat >"${RUNTIME_DIR}/runner.sh" <<'EOF_RUNNER'
#!/usr/bin/env bash
set -Eeuo pipefail
mode="$1"
state_file="$2"
count=0
[[ ! -s "${state_file}" ]] || count="$(cat "${state_file}")"
count=$((count + 1))
printf '%s\n' "${count}" >"${state_file}"
case "${mode}:${count}" in
    activating:1) sleep 300 ;;
    activating:*)
        systemd-notify --ready
        exec /bin/sleep infinity
        ;;
    recover:1) exit 1 ;;
    rollback:2) exit 1 ;;
esac
exec /bin/sleep infinity
EOF_RUNNER
    chmod 700 "${RUNTIME_DIR}/runner.sh"
}

write_unit() {
    local role="$1"
    local mode="$2"
    local unit
    local service_type="simple"
    local notify_access=""
    unit="$(unit_name "${role}")"

    if [[ "${role}" == "activating" ]]
    then
        service_type="notify"
        notify_access="NotifyAccess=all"
    fi

    cat >"${UNIT_DIR}/${unit}" <<EOF_UNIT
[Unit]
Description=DSM update homologation ${role}

[Service]
Type=${service_type}
${notify_access}
ExecStart=${RUNTIME_DIR}/runner.sh ${mode} ${RUNTIME_DIR}/${role}.count
Restart=no
TimeoutStartSec=330

[Install]
WantedBy=multi-user.target
EOF_UNIT
}

wait_for_state() {
    local unit="$1"
    local expected="$2"
    local deadline=$((SECONDS + 20))
    until [[ "$(systemctl show "${unit}" --property=ActiveState --value)" == "${expected}" ]]
    do
        (( SECONDS < deadline )) || fail "${unit} did not reach ${expected}"
        sleep 1
    done
}

assert_active() { systemctl is-active --quiet "$1" || fail "$1 is not active"; }
assert_inactive() { ! systemctl is-active --quiet "$1" || fail "$1 was started unexpectedly"; }

cleanup() {
    local role unit
    trap - EXIT
    for role in active activating failed disabled rollback
    do
        unit="$(unit_name "${role}")"
        systemctl disable --now "${unit}" >/dev/null 2>&1 || true
        rm -f -- "${UNIT_DIR}/${unit}"
    done
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl reset-failed >/dev/null 2>&1 || true
    [[ "${RUNTIME_DIR}" == /var/tmp/dsm-update-homologation-runtime-* ]] \
        && rm -rf -- "${RUNTIME_DIR}"
}
trap cleanup EXIT

capture_host_state before
capture_dsm_health before
CONFIG_BEFORE="$(sha256sum /opt/dsm/config/dsm.conf | awk '{print $1}')"
write_runner

# Success matrix: active, activating, failed+enabled and disabled+active.
write_unit active normal
write_unit activating activating
write_unit failed recover
write_unit disabled normal
systemctl daemon-reload
systemctl enable --now "$(unit_name active)"
systemctl enable "$(unit_name activating)" "$(unit_name failed)"
systemctl start --no-block "$(unit_name activating)"
systemctl start "$(unit_name failed)" >/dev/null 2>&1 || true
systemctl start "$(unit_name disabled)"
wait_for_state "$(unit_name active)" active
wait_for_state "$(unit_name activating)" activating
wait_for_state "$(unit_name failed)" failed
wait_for_state "$(unit_name disabled)" active
[[ "$(systemctl is-enabled "$(unit_name disabled)" 2>/dev/null || true)" == disabled ]] \
    || fail "disabled fixture is not disabled"

DSM_UPDATE_READINESS_TIMEOUT=90 DSM_UPDATE_READINESS_INTERVAL=1 \
    bash "${PACKAGE_ROOT}/update.sh" --yes --allow-same-version "${PACKAGE_ROOT}" \
    >"${UPDATE_LOG}" 2>&1 || fail "successful update scenario failed"
SUCCESS_UPDATE_DONE=1

assert_active "$(unit_name active)"
assert_active "$(unit_name activating)"
assert_active "$(unit_name failed)"
assert_inactive "$(unit_name disabled)"
[[ "$(systemctl is-enabled "$(unit_name disabled)" 2>/dev/null || true)" == disabled ]] \
    || fail "update changed disabled unit enablement"
[[ "$(sha256sum /opt/dsm/config/dsm.conf | awk '{print $1}')" == "${CONFIG_BEFORE}" ]] \
    || fail "configuration changed during same-version update"
capture_dsm_health after-success

# Rollback matrix: active+enabled on first start, fails during post-update
# restart, then succeeds when rollback restores the previous installation.
write_unit rollback rollback
systemctl daemon-reload
systemctl enable --now "$(unit_name rollback)"
assert_active "$(unit_name rollback)"
DIAGNOSTICS_BEFORE="$(find /opt/dsm-backups -maxdepth 1 -type d \
    -name 'update-diagnostics-*' -printf '%f\n' 2>/dev/null | sort || true)"
if DSM_UPDATE_READINESS_TIMEOUT=10 DSM_UPDATE_READINESS_INTERVAL=1 \
    bash "${PACKAGE_ROOT}/update.sh" --yes --allow-same-version "${PACKAGE_ROOT}" \
    >"${ROLLBACK_LOG}" 2>&1
then
    fail "controlled service failure did not fail the update"
fi
ROLLBACK_TEST_DONE=1

assert_active "$(unit_name rollback)"
[[ "$(tr -d '\r\n' </opt/dsm/version)" == "${VERSION_BEFORE}" ]] \
    || fail "rollback did not restore the previous version"
[[ "$(sha256sum /opt/dsm/config/dsm.conf | awk '{print $1}')" == "${CONFIG_BEFORE}" ]] \
    || fail "rollback did not restore configuration"
grep -q 'FALHA DURANTE A ATUALIZAÇÃO' "${ROLLBACK_LOG}" \
    || fail "failure path was not recorded"
grep -q 'Rollback concluído' "${ROLLBACK_LOG}" \
    || fail "rollback completion was not recorded"
DIAGNOSTICS_AFTER="$(find /opt/dsm-backups -maxdepth 1 -type d \
    -name 'update-diagnostics-*' -printf '%f\n' 2>/dev/null | sort || true)"
[[ "${DIAGNOSTICS_AFTER}" != "${DIAGNOSTICS_BEFORE}" ]] \
    || fail "failure diagnostics did not survive rollback"
comm -13 <(printf '%s\n' "${DIAGNOSTICS_BEFORE}") \
    <(printf '%s\n' "${DIAGNOSTICS_AFTER}") \
    >"${EVIDENCE_DIR}/rollback-diagnostic-directories.txt"
capture_dsm_health after-rollback
capture_host_state after

cat >"${RESULT_FILE}" <<EOF_RESULT
status=passed
test_id=${TEST_ID}
installed_version=${VERSION_BEFORE}
package_version=${PACKAGE_VERSION}
success_update_done=${SUCCESS_UPDATE_DONE}
rollback_test_done=${ROLLBACK_TEST_DONE}
evidence_dir=${EVIDENCE_DIR}
EOF_RESULT

printf 'PASS: DSM update homologation completed. Evidence: %s\n' "${EVIDENCE_DIR}"
