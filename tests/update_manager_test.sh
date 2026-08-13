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

echo "Update manager tests passed."
