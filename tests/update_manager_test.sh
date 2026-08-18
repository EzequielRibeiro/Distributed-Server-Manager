#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPDATE="${ROOT}/update.sh"

fail(){ echo "FAIL: $*" >&2; exit 1; }

HELP_OUTPUT=$(bash "${UPDATE}" --help)
grep -q '^Usage:' <<<"${HELP_OUTPUT}" || fail "help unavailable without root"
if bash "${UPDATE}" --invalid >/dev/null 2>&1; then fail "unknown option accepted"; fi
if bash "${UPDATE}" first second >/dev/null 2>&1; then fail "multiple package directories accepted"; fi
grep -q -- '--allow-same-version' <<<"${HELP_OUTPUT}" || fail "same-version override missing from help"
grep -q -- '--allow-downgrade' <<<"${HELP_OUTPUT}" || fail "downgrade override missing from help"

(
    source "${UPDATE}"
    [[ "$(semver_compare 1.1.0 1.0.0)" == "1" ]] || fail "upgrade comparison failed"
    [[ "$(semver_compare 1.0.0 1.0.0)" == "0" ]] || fail "equal comparison failed"
    [[ "$(semver_compare 1.0.0-rc.1 1.0.0)" == "-1" ]] || fail "prerelease comparison failed"
    [[ "$(semver_compare 1.0.0-rc.2 1.0.0-rc.10)" == "-1" ]] || fail "numeric prerelease comparison failed"
)

(
    source "${UPDATE}"
    OLD_VERSION="1.0.0"
    NEW_VERSION="1.1.0"
    enforce_version_policy
) >/dev/null || fail "valid upgrade was blocked"

if (
    source "${UPDATE}"
    OLD_VERSION="1.1.0"
    NEW_VERSION="1.1.0"
    enforce_version_policy
) >/dev/null 2>&1; then
    fail "same version was accepted without override"
fi

(
    source "${UPDATE}"
    OLD_VERSION="1.1.0"
    NEW_VERSION="1.1.0"
    ALLOW_SAME_VERSION=1
    enforce_version_policy
) >/dev/null || fail "same-version override was ignored"

if (
    source "${UPDATE}"
    OLD_VERSION="1.1.0"
    NEW_VERSION="1.0.0"
    enforce_version_policy
) >/dev/null 2>&1; then
    fail "downgrade was accepted without override"
fi

(
    source "${UPDATE}"
    OLD_VERSION="1.1.0"
    NEW_VERSION="1.0.0"
    ALLOW_DOWNGRADE=1
    enforce_version_policy
) >/dev/null || fail "downgrade override was ignored"

for item in config data runtime instances packages custom mods tools import export; do
    grep -q "^[[:space:]]*\"${item}\"" "${UPDATE}" || fail "mutable directory not preserved: ${item}"
done
grep -Fq 'rsync -a "${INSTALL_DIR}/${ITEM}/" "${STAGING_DIR}/${ITEM}/"' "${UPDATE}" || fail "preservation can nest directories"
grep -Fq 'find "${INSTALL_DIR}" -mindepth 1 -maxdepth 1 -print0' "${UPDATE}" || fail "unmanaged local data is not discovered"
grep -Fq 'tar -xzf "${BACKUP_FILE}" -C /opt' "${UPDATE}" || fail "rollback restores outside /opt"
grep -Fq 'REQUIRED_BYTES=$((INSTALL_BYTES * 2))' "${UPDATE}" || fail "disk check ignores installation size"
grep -Fq 'gzip -t "${BACKUP_PART}"' "${UPDATE}" || fail "backup integrity is not validated"
grep -Fq 'mv -- "${BACKUP_PART}" "${BACKUP_FILE}"' "${UPDATE}" || fail "backup is not activated atomically"
grep -Fq -- '--exclude="${INSTALL_NAME}/game-data"' "${UPDATE}" || fail "downloadable game data is included in backup"
grep -Fq 'mv "${INSTALL_DIR}/game-data" "${GAME_DATA_ROLLBACK}"' "${UPDATE}" || fail "rollback does not preserve game data"
grep -Fq 'wait_with_progress' "${UPDATE}" || fail "backup progress is not displayed"
grep -Fq 'cd "$(dirname "${INSTALL_DIR}")"' "${UPDATE}" || fail "update can keep a deleted installation as working directory"
grep -Fq 'validate_runtime_account' "${UPDATE}" || fail "DSM runtime account is not validated"
grep -Fq 'migrate_database' "${UPDATE}" || fail "database migrations are not part of the update"
grep -Fq 'create_database_backup' "${UPDATE}" || fail "network database backup is missing"
grep -Fq 'restore_database_backup' "${UPDATE}" || fail "network database rollback is missing"
grep -Fq -- '--confirm-restore' "${UPDATE}" || fail "database restore lacks destructive confirmation"
grep -Fq 'export DSM_DATABASE_DRIVER' "${UPDATE}" || fail "runtime database configuration is not exported"
if grep -Fq -- '--database "${DATABASE}" migrate' "${UPDATE}"; then
    fail "update migrations are forced to SQLite"
fi
grep -Fq 'id -u "${DSM_USER}"' "${UPDATE}" || fail "DSM user existence is not checked"
grep -Fq 'getent group "${DSM_GROUP}"' "${UPDATE}" || fail "DSM group existence is not checked"
grep -Fq 'capture_service_state' "${UPDATE}" || fail "active service state is not captured"
grep -Fq 'for SERVICE_NAME in "${ACTIVE_SERVICES[@]}"' "${UPDATE}" || fail "service restart state is not preserved"
if grep -Fq 'systemctl enable "${SERVICE_NAME}"' "${UPDATE}"; then
    fail "update manager enables every discovered service"
fi
grep -Fq 'ExecStart=/opt/dsm/runtime/workers/sync_worker.sh' "${ROOT}/systemd/dsm-runtime-sync.service" \
    || fail "runtime sync service points to a missing worker"
grep -Fq 'Type=oneshot' "${ROOT}/systemd/dsm-runtime-sync.service" \
    || fail "runtime sync worker is configured as a long-running service"
grep -Fq 'ExecStart=/bin/bash /opt/dsm/dashboard/workers/worker.sh' \
    "${ROOT}/systemd/dsm-dashboard-worker.service" \
    || fail "dashboard worker service points to a missing launcher"
grep -Fq 'start_worker dashboard_worker.sh' "${ROOT}/dashboard/workers/worker.sh" \
    || fail "dashboard aggregate state worker is not started"
grep -Fq 'migrate_dashboard_worker_services' "${UPDATE}" \
    || fail "legacy dashboard worker services are not migrated"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

STATE_ROOT="${TMP_DIR}/dashboard-state-root"
DSM_ROOT="${STATE_ROOT}" bash "${ROOT}/dashboard/state/init_state.sh" >/dev/null
for state_name in dashboard server metrics monitor alerts doctor scheduler events; do
    [[ -f "${STATE_ROOT}/dashboard/state/${state_name}_state.json" ]] \
        || fail "missing initialized dashboard state: ${state_name}"
done
if find "${STATE_ROOT}/dashboard/state" -maxdepth 1 -name '*.state.json' | grep -q .; then
    fail "dashboard states use the obsolete .state.json naming"
fi

mkdir -p "${TMP_DIR}/opt/dsm/instances/server01"
printf 'world' >"${TMP_DIR}/opt/dsm/instances/server01/world.dat"
tar -czf "${TMP_DIR}/backup.tar.gz" -C "${TMP_DIR}/opt" dsm
rm -rf -- "${TMP_DIR}/opt/dsm"
tar -xzf "${TMP_DIR}/backup.tar.gz" -C "${TMP_DIR}/opt"
[[ -f "${TMP_DIR}/opt/dsm/instances/server01/world.dat" ]] || fail "rollback archive layout invalid"

(
    # shellcheck source=../update.sh
    source "${UPDATE}"
    INSTALL_DIR="${TMP_DIR}/source/opt/dsm"
    BACKUP_DIR="${TMP_DIR}/generated-backups"
    BACKUP_FILE=""
    BACKUP_PART=""
    BACKUP_PROCESS_PID=""
    mkdir -p "${INSTALL_DIR}/instances/server01"
    mkdir -p "${INSTALL_DIR}/game-data/dayz"
    printf 'world' >"${INSTALL_DIR}/instances/server01/world.dat"
    printf 'downloadable' >"${INSTALL_DIR}/game-data/dayz/server.bin"

    create_backup >/dev/null

    [[ -f "${BACKUP_FILE}" ]] || fail "validated backup was not created"
    [[ ! -e "${BACKUP_FILE}.part" ]] || fail "partial backup was not activated"
    gzip -t "${BACKUP_FILE}" || fail "generated backup is corrupt"
    tar -xOf "${BACKUP_FILE}" dsm/instances/server01/world.dat \
        | grep -q '^world$' || fail "generated backup has an invalid archive layout"
    if tar -tzf "${BACKUP_FILE}" | grep -q '^dsm/game-data/'; then
        fail "generated backup contains downloadable game data"
    fi
)

(
    # Validate the account checks without depending on host account names.
    source "${UPDATE}"
    CONFIG_FILE="${TMP_DIR}/dsm.conf"
    DSM_USER="node1"
    DSM_GROUP="node1"
    DSM_HOME="${TMP_DIR}/home/node1"
    mkdir -p "${DSM_HOME}"
    id() {
        [[ "$1" == "-u" && "$2" == "node1" ]] || return 1
        printf '1000\n'
    }
    getent() {
        case "$1:$2" in
            group:node1) printf 'node1:x:1000:\n' ;;
            passwd:node1) printf 'node1:x:1000:1000::%s:/bin/bash\n' "${DSM_HOME}" ;;
            *) return 2 ;;
        esac
    }
    validate_runtime_account >/dev/null
)

if (
    source "${UPDATE}"
    CONFIG_FILE="${TMP_DIR}/dsm.conf"
    DSM_USER="missing-user"
    DSM_GROUP="missing-group"
    DSM_HOME="${TMP_DIR}/home/missing-user"
    id() { return 1; }
    validate_runtime_account >/dev/null 2>&1
); then
    fail "missing DSM user was accepted"
fi

(
    source "${UPDATE}"
    SYSTEMD_DIR="${TMP_DIR}/systemd"
    SYSTEMD_ENABLED=1
    SYSTEMCTL_LOG="${TMP_DIR}/systemctl.log"
    mkdir -p "${SYSTEMD_DIR}"
    : >"${SYSTEMD_DIR}/dsm-active.service"
    : >"${SYSTEMD_DIR}/dsm-inactive.service"
    : >"${SYSTEMCTL_LOG}"
    systemctl() {
        if [[ "$1" == "is-active" ]]
        then
            [[ "$3" == "dsm-active.service" ]]
            return
        fi
        printf '%s\n' "$*" >>"${SYSTEMCTL_LOG}"
    }

    capture_service_state >/dev/null
    [[ "${#ACTIVE_SERVICES[@]}" -eq 1 ]] || fail "incorrect number of active services captured"
    [[ "${ACTIVE_SERVICES[0]}" == "dsm-active.service" ]] || fail "inactive service was captured"

    stop_services >/dev/null
    restart_services >/dev/null
    grep -q '^stop dsm-active.service$' "${SYSTEMCTL_LOG}" || fail "active service was not stopped"
    grep -q '^start dsm-active.service$' "${SYSTEMCTL_LOG}" || fail "active service was not restarted"
    if grep -q 'dsm-inactive.service' "${SYSTEMCTL_LOG}"
    then
        fail "inactive service state was changed"
    fi
)

(
    source "${UPDATE}"
    SYSTEMD_DIR="${TMP_DIR}/migration-systemd"
    SYSTEMD_ENABLED=1
    SYSTEMCTL_LOG="${TMP_DIR}/migration-systemctl.log"
    mkdir -p "${SYSTEMD_DIR}"
    for unit in \
        dsm-dashboard-worker.service \
        dsm-backup-worker.service \
        dsm-events-worker.service \
        dsm-metrics-worker.service \
        dsm-mods-worker.service \
        dsm-server-worker.service
    do
        : >"${SYSTEMD_DIR}/${unit}"
    done
    : >"${SYSTEMCTL_LOG}"
    ACTIVE_SERVICES=(
        dsm-metrics-worker.service
        dsm-event-queue-worker.service
    )
    systemctl() {
        printf '%s\n' "$*" >>"${SYSTEMCTL_LOG}"
    }

    migrate_dashboard_worker_services >/dev/null

    [[ "${ACTIVE_SERVICES[*]}" == \
        "dsm-event-queue-worker.service dsm-dashboard-worker.service" ]] \
        || fail "legacy active workers were not consolidated"
    grep -q '^disable --now dsm-metrics-worker.service$' "${SYSTEMCTL_LOG}" \
        || fail "legacy metrics worker was not disabled"
    grep -q '^enable dsm-dashboard-worker.service$' "${SYSTEMCTL_LOG}" \
        || fail "dashboard aggregate worker was not enabled"

    migrate_dashboard_worker_services >/dev/null
    [[ "${ACTIVE_SERVICES[*]}" == \
        "dsm-event-queue-worker.service dsm-dashboard-worker.service" ]] \
        || fail "dashboard worker migration is not idempotent"
)

(
    source "${UPDATE}"
    CONFIG_FILE="${TMP_DIR}/versioned-dsm.conf"
    NEW_VERSION="1.1.0"
    printf 'DSM_VERSION="1.0.0"\nINSTALLER_VERSION="1.0.0"\nLOCAL_SETTING="preserved"\n' \
        >"${CONFIG_FILE}"
    update_configuration_version
    grep -q '^DSM_VERSION="1.1.0"$' "${CONFIG_FILE}" || fail "DSM config version was not updated"
    grep -q '^INSTALLER_VERSION="1.1.0"$' "${CONFIG_FILE}" || fail "installer config version was not updated"
    grep -q "^DSM_DATA_DIR=\"${INSTALL_DIR}/data\"$" "${CONFIG_FILE}" || fail "data directory was not configured"
    grep -q "^DSM_DATABASE=\"${INSTALL_DIR}/data/capivara.db\"$" "${CONFIG_FILE}" || fail "database path was not configured"
    grep -q '^LOCAL_SETTING="preserved"$' "${CONFIG_FILE}" || fail "local configuration was overwritten"
)

# =============================================================
# Update Manager semantic version contract
# =============================================================

UPDATE_MANAGER="${ROOT}/update-manager/update-manager.sh"

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    [[ "$(semver_compare 1.1.0 1.0.0)" == "1" ]] \
        || fail "update manager upgrade comparison failed"

    [[ "$(semver_compare 1.0.0 1.0.0)" == "0" ]] \
        || fail "update manager equal-version comparison failed"

    [[ "$(semver_compare 1.0.0 1.1.0)" == "-1" ]] \
        || fail "update manager downgrade comparison failed"

    [[ "$(semver_compare 1.0.0-rc.1 1.0.0)" == "-1" ]] \
        || fail "update manager prerelease comparison failed"

    [[ "$(semver_compare 1.0.0-rc.2 1.0.0-rc.10)" == "-1" ]] \
        || fail "update manager numeric prerelease comparison failed"
)

# =============================================================
# Update Manager update-check contract
# =============================================================

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    TEST_INSTALL_DIR="$(mktemp -d)"
    INSTALL_DIR="${TEST_INSTALL_DIR}"

    trap 'rm -rf -- "${TEST_INSTALL_DIR}"' EXIT

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    notify_dispatch()
    {
        :
    }

    github_latest_release()
    {
        printf '%s\n' '{"tag_name":"v1.0.0"}'
    }

    printf '%s\n' '1.0.0' >"${INSTALL_DIR}/version"

    dsm_update_check >/dev/null \
        || fail "equal release should report DSM as up to date"
)

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    TEST_INSTALL_DIR="$(mktemp -d)"
    INSTALL_DIR="${TEST_INSTALL_DIR}"

    trap 'rm -rf -- "${TEST_INSTALL_DIR}"' EXIT

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    notify_dispatch()
    {
        :
    }

    github_latest_release()
    {
        printf '%s\n' '{"tag_name":"v1.1.0"}'
    }

    printf '%s\n' '1.0.0' >"${INSTALL_DIR}/version"

    set +e
    dsm_update_check >/dev/null
    STATUS=$?
    set -e

    [[ "${STATUS}" -eq 10 ]] \
        || fail "newer release should return 10; returned ${STATUS}"
)

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    TEST_INSTALL_DIR="$(mktemp -d)"
    INSTALL_DIR="${TEST_INSTALL_DIR}"

    trap 'rm -rf -- "${TEST_INSTALL_DIR}"' EXIT

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    notify_dispatch()
    {
        :
    }

    github_latest_release()
    {
        printf '%s\n' '{"tag_name":"v1.0.0"}'
    }

    printf '%s\n' '1.1.0' >"${INSTALL_DIR}/version"

    dsm_update_check >/dev/null \
        || fail "installed version ahead of release should not be treated as an update"
)

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    TEST_INSTALL_DIR="$(mktemp -d)"
    INSTALL_DIR="${TEST_INSTALL_DIR}"

    trap 'rm -rf -- "${TEST_INSTALL_DIR}"' EXIT

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    notify_dispatch()
    {
        :
    }

    github_latest_release()
    {
        printf '%s\n' '{"tag_name":"v1.1.0"}'
    }

    printf '%s\n' 'invalid-version' >"${INSTALL_DIR}/version"

    if dsm_update_check >/dev/null 2>&1
    then
        fail "invalid installed version was accepted"
    fi
)

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    TEST_INSTALL_DIR="$(mktemp -d)"
    INSTALL_DIR="${TEST_INSTALL_DIR}"

    trap 'rm -rf -- "${TEST_INSTALL_DIR}"' EXIT

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    notify_dispatch()
    {
        :
    }

    github_latest_release()
    {
        printf '%s\n' '{"tag_name":"not-semver"}'
    }

    printf '%s\n' '1.0.0' >"${INSTALL_DIR}/version"

    if dsm_update_check >/dev/null 2>&1
    then
        fail "invalid remote version was accepted"
    fi
)

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    TEST_INSTALL_DIR="$(mktemp -d)"
    INSTALL_DIR="${TEST_INSTALL_DIR}"

    trap 'rm -rf -- "${TEST_INSTALL_DIR}"' EXIT

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    notify_dispatch()
    {
        :
    }

    github_latest_release()
    {
        printf '%s\n' '{"tag_name":null}'
    }

    printf '%s\n' '1.0.0' >"${INSTALL_DIR}/version"

    if dsm_update_check >/dev/null 2>&1
    then
        fail "release without tag_name was accepted"
    fi
)

# =============================================================
# Update Manager update-run gate contract
# =============================================================

# Up to date:
# dsm_update_run must stop successfully without entering
# the download/install pipeline.
(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    PIPELINE_CALLED=0

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    dsm_update_check()
    {
        return 0
    }

    github_latest_release()
    {
        PIPELINE_CALLED=1
        return 1
    }

    dsm_update_run >/dev/null \
        || fail "update run should succeed when DSM is already up to date"

    [[ "${PIPELINE_CALLED}" -eq 0 ]] \
        || fail "update run entered pipeline for an up-to-date installation"
)

# Check failure:
# dsm_update_run must convert a check failure into a normal
# update-run failure and must not enter the pipeline.
(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    PIPELINE_CALLED=0

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    dsm_update_check()
    {
        return 1
    }

    github_latest_release()
    {
        PIPELINE_CALLED=1
        return 1
    }

    if dsm_update_run >/dev/null 2>&1
    then
        fail "update run accepted an update-check failure"
    fi

    [[ "${PIPELINE_CALLED}" -eq 0 ]] \
        || fail "update run entered pipeline after update-check failure"
)

# Update available:
# return 10 from dsm_update_check is the only status that
# authorizes dsm_update_run to enter the update pipeline.
# Update available:
# return 10 from dsm_update_check is the only status that
# authorizes dsm_update_run to enter the update pipeline.
(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    TEST_INSTALL_DIR="$(mktemp -d)"
    PIPELINE_MARKER="${TEST_INSTALL_DIR}/pipeline-called"
    INSTALL_DIR="${TEST_INSTALL_DIR}"

    trap 'rm -rf -- "${TEST_INSTALL_DIR}"' EXIT

    printf '%s\n' '1.0.0' >"${INSTALL_DIR}/version"

    log_info()
    {
        :
    }

    log_error()
    {
        :
    }

    notify_dispatch()
    {
        :
    }

    dsm_update_check()
    {
        return 10
    }

    github_latest_release()
    {
        touch "${PIPELINE_MARKER}"
        printf '%s\n' '{"tag_name":"v1.1.0"}'
    }

    github_release_download()
    {
        # Deliberately stop the pipeline immediately after
        # proving that status 10 allowed it to advance.
        printf '%s\n' ''
    }

    if dsm_update_run >/dev/null 2>&1
    then
        fail "update run unexpectedly completed without a release package"
    fi

    [[ -f "${PIPELINE_MARKER}" ]] \
        || fail "update run did not enter pipeline when update-check returned 10"
)

# =============================================================
# Update Manager checksum fail-closed contract
# =============================================================

(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/verify-release.sh
    source "${ROOT}/update-manager/verify-release.sh"

    TEST_ROOT="$(mktemp -d)"
    PACKAGE_VERSION="1.0.0"
    PACKAGE_NAME="capivara-dsm-${PACKAGE_VERSION}"
    PACKAGE_ROOT="${TEST_ROOT}/${PACKAGE_NAME}"
    PACKAGE="${TEST_ROOT}/${PACKAGE_NAME}.tar.gz"

    trap 'rm -rf -- "${TEST_ROOT}"' EXIT

    mkdir -p \
        "${PACKAGE_ROOT}/bin" \
        "${PACKAGE_ROOT}/core"

    printf '%s\n' "${PACKAGE_VERSION}" >"${PACKAGE_ROOT}/version"
    printf '%s\n' '#!/usr/bin/env bash' >"${PACKAGE_ROOT}/bin/dsm"
    printf '%s\n' '#!/usr/bin/env bash' >"${PACKAGE_ROOT}/core/bootstrap.sh"

    tar -czf "${PACKAGE}" -C "${TEST_ROOT}" "${PACKAGE_NAME}"

    VERIFY_CHECKSUM=1

    log_error()
    {
        :
    }

    VALID_CHECKSUM="$(sha256sum "${PACKAGE}" | awk '{print $1}')"
    INVALID_CHECKSUM="$(printf '0%.0s' {1..64})"

    verify_release "${PACKAGE}" "${VALID_CHECKSUM}" >/dev/null \
        || fail "valid release checksum was rejected"

    if verify_release "${PACKAGE}" "${INVALID_CHECKSUM}" >/dev/null 2>&1
    then
        fail "invalid release checksum was accepted"
    fi

    if verify_release "${PACKAGE}" "" >/dev/null 2>&1
    then
        fail "missing release checksum was accepted"
    fi
)

# =============================================================
# Update Manager pipeline checksum fail-closed integration
# =============================================================
(
    DSM_ROOT="${ROOT}"

    # shellcheck source=../update-manager/update-manager.sh
    source "${UPDATE_MANAGER}"

    PIPELINE_ROOT="$(mktemp -d)"
    trap 'rm -rf -- "${PIPELINE_ROOT}"' EXIT
    PIPELINE_INSTALL="${PIPELINE_ROOT}/install"
    PIPELINE_DOWNLOADS="${PIPELINE_ROOT}/downloads"
    PIPELINE_TEMP="${PIPELINE_ROOT}/tmp"

    mkdir -p \
        "${PIPELINE_INSTALL}" \
        "${PIPELINE_DOWNLOADS}" \
        "${PIPELINE_TEMP}"

    printf '%s\n' '1.0.0' >"${PIPELINE_INSTALL}/version"

    PIPELINE_PACKAGE="${PIPELINE_DOWNLOADS}/dsm.tar.gz"
    PIPELINE_CHECKSUM="${PIPELINE_DOWNLOADS}/dsm.tar.gz.sha256"
    UPDATE_MARKER="${PIPELINE_ROOT}/update-called"
    EVENT_LOG="${PIPELINE_ROOT}/events.log"

    printf '%s\n' 'corrupted package' >"${PIPELINE_PACKAGE}"

    VALID_FORMAT_INVALID_CHECKSUM="$(
        printf '0%.0s' {1..64}
    )"

    printf '%s  %s\n' \
        "${VALID_FORMAT_INVALID_CHECKSUM}" \
        "dsm.tar.gz" \
        >"${PIPELINE_CHECKSUM}"

    INSTALL_DIR="${PIPELINE_INSTALL}"
    TEMP_DIR="${PIPELINE_TEMP}"

    dsm_update_check()
    {
        latest_version="2.0.0"
        return 10
    }

    github_latest_release()
    {
        printf '%s\n' '{"tag_name":"v2.0.0"}'
    }

    github_release_download()
    {
        printf '%s\n' 'https://example.invalid/dsm.tar.gz'
    }

    download_release()
    {
        printf '%s\n' "${PIPELINE_PACKAGE}"
    }

    github_release_checksum_download()
    {
        printf '%s\n' 'https://example.invalid/dsm.tar.gz.sha256'
    }

    download_checksum()
    {
        printf '%s\n' "${PIPELINE_CHECKSUM}"
    }

    notify_dispatch()
    {
        :
    }

    events_emit()
    {
        printf '%s\n' "$*" >>"${EVENT_LOG}"
    }

    verify_release()
    {
        return 1
    }

    dsm_update_history_add()
    {
        fail "history was written after checksum validation failure"
    }

    update_guard()
    {
        touch "${UPDATE_MARKER}"
        return 0
    }

    DSM_ROOT="${PIPELINE_ROOT}/dsm-root"

    mkdir -p "${DSM_ROOT}"

    cat >"${DSM_ROOT}/update.sh" <<EOF
#!/usr/bin/env bash
touch "${UPDATE_MARKER}"
exit 0
EOF

    chmod +x "${DSM_ROOT}/update.sh"

    if dsm_update_run >/dev/null 2>&1
    then
        fail "update pipeline accepted failed checksum validation"
    fi

    [ ! -e "${UPDATE_MARKER}" ] \
        || fail "update.sh executed after checksum validation failure"

    [ -f "${EVENT_LOG}" ] \
        || fail "DSM_UPDATE_FAILED event was not emitted"

    grep -q '^DSM_UPDATE_FAILED 2\.0\.0$' "${EVENT_LOG}" \
        || fail "wrong event emitted after checksum validation failure"
)

# =============================================================
# Update Process Guard permanent contract
# =============================================================

PROCESS_GUARD="${ROOT}/update-manager/process-guard.sh"

[[ -f "${PROCESS_GUARD}" ]] \
    || fail "update Process Guard module is missing"

grep -Fq 'GUARD="${NEW_SRC}/update-manager/process-guard.sh"' "${UPDATE}" \
    || fail "update.sh does not load the Process Guard from the release source"

[[ "$(
    grep -Ec '^run_process_guard\(\)$' "${UPDATE}"
)" -eq 1 ]] \
    || fail "run_process_guard function must exist exactly once"

[[ "$(
    grep -Ec '^[[:space:]]+run_process_guard[[:space:]]*$' "${UPDATE}"
)" -eq 1 ]] \
    || fail "run_process_guard must be called exactly once"

grep -Fq 'process_guard_pre_update' "${UPDATE}" \
    || fail "update.sh does not invoke the Process Guard pre-update gate"

(
    guard_line="$(
        grep -nE '^[[:space:]]+run_process_guard[[:space:]]*$' \
            "${UPDATE}" |
        cut -d: -f1
    )"

    capture_line="$(
        grep -nE '^[[:space:]]+capture_service_state[[:space:]]*$' \
            "${UPDATE}" |
        cut -d: -f1
    )"

    transaction_line="$(
        grep -nE '^[[:space:]]+UPDATE_TRANSACTION_STARTED=1[[:space:]]*$' \
            "${UPDATE}" |
        cut -d: -f1
    )"

    stop_line="$(
        grep -nE '^[[:space:]]+stop_services[[:space:]]*$' \
            "${UPDATE}" |
        cut -d: -f1
    )"

    [[ "${guard_line}" =~ ^[0-9]+$ ]] \
        || fail "Process Guard call line was not found"

    [[ "${capture_line}" =~ ^[0-9]+$ ]] \
        || fail "capture_service_state call line was not found"

    [[ "${transaction_line}" =~ ^[0-9]+$ ]] \
        || fail "update transaction marker line was not found"

    [[ "${stop_line}" =~ ^[0-9]+$ ]] \
        || fail "stop_services call line was not found"

    (( guard_line < capture_line )) \
        || fail "Process Guard runs after service state capture"

    (( capture_line < transaction_line )) \
        || fail "update transaction starts before service state capture"

    (( transaction_line < stop_line )) \
        || fail "DSM services stop before update transaction starts"
)

(
    while IFS= read -r line
    do
        trimmed="$(
            printf '%s\n' "${line}" |
                sed 's/^[[:space:]]*//'
        )"

        case "${trimmed}" in
            pkill|pkill\ *|killall|killall\ *)
                fail "Process Guard contains destructive process termination"
                ;;
            kill\ *)
                if [[ ! "${trimmed}" =~ ^kill[[:space:]]+-0([[:space:]]|$) ]]
                then
                    fail "Process Guard contains destructive kill command"
                fi
                ;;
        esac

    done <"${PROCESS_GUARD}"
)

(
    TEST_ROOT="$(mktemp -d)"
    TEST_PID=""

    cleanup_process_guard_test()
    {
        if [[ -n "${TEST_PID}" ]] &&
           kill -0 "${TEST_PID}" 2>/dev/null
        then
            wait "${TEST_PID}" 2>/dev/null || true
        fi

        rm -rf -- "${TEST_ROOT}"
    }

    trap cleanup_process_guard_test EXIT

    export DSM_ROOT="${TEST_ROOT}"

    TEST_CGROUP_ROOT="${TEST_ROOT}/cgroup"

    export PROCESS_GUARD_CGROUP_ROOT="${TEST_CGROUP_ROOT}"

    # shellcheck source=../update-manager/process-guard.sh
    source "${PROCESS_GUARD}"

    INSTANCE_PATH="${DSM_ROOT}/instances/TestNode/dayz/test-instance"
    PIDFILE="${INSTANCE_PATH}/runtime/process.pid"

    mkdir -p "${INSTANCE_PATH}/runtime"

    ACTIVE="$(process_guard_active_instances)"

    [[ -z "${ACTIVE}" ]] \
        || fail "Process Guard reports an active instance without a process"

    sleep 2 &
    TEST_PID=$!

    printf '%s\n' "${TEST_PID}" >"${PIDFILE}"

    ACTIVE="$(process_guard_active_instances)"

    [[ -n "${ACTIVE}" ]] \
        || fail "Process Guard did not detect an active instance"

    grep -Fq "${TEST_PID}" <<<"${ACTIVE}" \
        || fail "Process Guard active instance output lacks the PID"

    grep -Fq "test-instance" <<<"${ACTIVE}" \
        || fail "Process Guard active instance output lacks the instance"

    if process_guard_assert_no_active_instances >/dev/null 2>&1
    then
        fail "Process Guard allowed update with an active game instance"
    fi

    wait "${TEST_PID}"
    TEST_PID=""

    ACTIVE="$(process_guard_active_instances)"

    [[ -z "${ACTIVE}" ]] \
        || fail "Process Guard treats a stale PID as active"

    process_guard_assert_no_active_instances >/dev/null \
        || fail "Process Guard blocks update without active instances"

    # ---------------------------------------------------------
    # Active transient systemd unit without instance directory
    #
    # Reproduz o caso real observado no Linux:
    #
    #   capivara-instance-<id>.service
    #
    # permanece ativa mesmo depois que o diretório original
    # da instância deixou de existir.
    # ---------------------------------------------------------

    ORPHAN_UNIT="capivara-instance-orphan-dayz.service"

    ORPHAN_CGROUP="${TEST_CGROUP_ROOT}/user.slice/user-test.slice/app.slice/${ORPHAN_UNIT}"

    mkdir -p "${ORPHAN_CGROUP}"

    sleep 2 &
    TEST_PID=$!

    printf '%s\n' "${TEST_PID}" \
        >"${ORPHAN_CGROUP}/cgroup.procs"

    ACTIVE="$(process_guard_active_instances)"

    [[ -n "${ACTIVE}" ]] \
        || fail "Process Guard did not detect an active transient unit"

    grep -Fq "${TEST_PID}" <<<"${ACTIVE}" \
        || fail "Process Guard transient unit output lacks the PID"

    grep -Fq "${ORPHAN_UNIT}" <<<"${ACTIVE}" \
        || fail "Process Guard transient unit output lacks the unit name"

    if process_guard_assert_no_active_instances >/dev/null 2>&1
    then
        fail "Process Guard allowed update with an orphan active transient unit"
    fi

    wait "${TEST_PID}"
    TEST_PID=""

    ACTIVE="$(process_guard_active_instances)"

    [[ -z "${ACTIVE}" ]] \
        || fail "Process Guard treats an empty transient cgroup as active"

    process_guard_assert_no_active_instances >/dev/null \
        || fail "Process Guard blocks update after transient unit becomes empty"
)
echo "Update manager tests passed."
