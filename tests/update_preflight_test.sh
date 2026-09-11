#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_PREFLIGHT="${ROOT}/update-manager/preflight.sh"
LATEST_PREFLIGHT="${ROOT}/update-manager/preflight-latest.sh"
DSM_COMPAT="${ROOT}/bin/dsm-compat"

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

bash -n "${TARGET_PREFLIGHT}"
bash -n "${LATEST_PREFLIGHT}"

# The public wrapper may use the network and /tmp, but never the installed
# update cache or the mutating update pipeline.
grep -Fq 'mktemp -d -t capivara-update-preflight.' "${LATEST_PREFLIGHT}" \
    || fail "latest preflight does not use an isolated temporary workspace"
grep -Fq 'verify_release "${package}" "${checksum}"' "${LATEST_PREFLIGHT}" \
    || fail "latest preflight does not validate the release before extraction"
grep -Fq 'bash "${target_preflight}" "${package_root}" "${INSTALL_DIR}"' "${LATEST_PREFLIGHT}" \
    || fail "latest preflight does not execute the target release contract"
grep -Fq 'github_release_channel "${release_json}"' "${LATEST_PREFLIGHT}" \
    || fail "latest preflight does not enforce the configured release channel"

for forbidden in \
    'download_release ' \
    'download_checksum ' \
    'CACHE_DIR' \
    'dsm_update_run' \
    'systemctl stop' \
    'systemctl restart'
do
    if grep -Fq "${forbidden}" "${LATEST_PREFLIGHT}"
    then
        fail "latest preflight contains mutating/cache path: ${forbidden}"
    fi
done

# The target-release contract itself must stay read-only with respect to the
# installed tree and service/database lifecycle.
for forbidden in \
    'rm -rf "${INSTALL_ROOT}"' \
    'mv -T -- "${INSTALL_ROOT}' \
    'systemctl stop' \
    'systemctl start' \
    'systemctl restart' \
    ' manager.py" --root "${INSTALL_ROOT}" migrate' \
    'create_backup' \
    'migrate_database'
do
    if grep -Fq "${forbidden}" "${TARGET_PREFLIGHT}"
    then
        fail "target preflight contains mutating operation: ${forbidden}"
    fi
done

grep -Fq 'process_guard_pre_update' "${TARGET_PREFLIGHT}" \
    || fail "target preflight does not reuse the target database/process guard"
grep -Fq 'UPDATE PREFLIGHT READY' "${TARGET_PREFLIGHT}" \
    || fail "target preflight success contract is missing"
grep -Fq 'cap update preflight' "${DSM_COMPAT}" \
    || fail "preflight is not exposed by the update CLI dispatcher"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

make_fixture()
{
    local installed_version="$1"
    local target_version="$2"
    local install_root="${TMP_DIR}/install"
    local target_root="${TMP_DIR}/target"

    rm -rf -- "${install_root}" "${target_root}"
    mkdir -p \
        "${install_root}/config" \
        "${install_root}/instances" \
        "${target_root}/bin" \
        "${target_root}/core" \
        "${target_root}/database" \
        "${target_root}/update-manager"

    printf '%s\n' "${installed_version}" >"${install_root}/version"
    printf '%s\n' "${target_version}" >"${target_root}/version"
    cp "${ROOT}/core/semver.sh" "${target_root}/core/semver.sh"
    : >"${target_root}/bin/cap"
    : >"${target_root}/core/bootstrap.sh"
    : >"${target_root}/database/manager.py"
    : >"${target_root}/update.sh"
    : >"${target_root}/update-manager/process-guard.sh"

    printf '%s\n%s\n' "${install_root}" "${target_root}"
}

mapfile -t FIXTURE < <(make_fixture 2.0.44 2.0.45)
INSTALL_ROOT="${FIXTURE[0]}"
TARGET_ROOT="${FIXTURE[1]}"
(
    source "${TARGET_PREFLIGHT}" "${TARGET_ROOT}" "${INSTALL_ROOT}"
    preflight_validate_target_package >/dev/null
    preflight_validate_versions >/dev/null
    preflight_validate_preserved_data >/dev/null
    preflight_validate_disk >/dev/null
) || fail "valid upgrade fixture failed read-only preflight primitives"

mapfile -t FIXTURE < <(make_fixture 2.0.44 2.0.44)
INSTALL_ROOT="${FIXTURE[0]}"
TARGET_ROOT="${FIXTURE[1]}"
if (
    source "${TARGET_PREFLIGHT}" "${TARGET_ROOT}" "${INSTALL_ROOT}"
    preflight_validate_versions >/dev/null 2>&1
)
then
    fail "same-version target passed preflight"
fi

mapfile -t FIXTURE < <(make_fixture 2.0.44 2.0.43)
INSTALL_ROOT="${FIXTURE[0]}"
TARGET_ROOT="${FIXTURE[1]}"
if (
    source "${TARGET_PREFLIGHT}" "${TARGET_ROOT}" "${INSTALL_ROOT}"
    preflight_validate_versions >/dev/null 2>&1
)
then
    fail "downgrade target passed preflight"
fi

mapfile -t FIXTURE < <(make_fixture 2.0.44 2.0.45)
INSTALL_ROOT="${FIXTURE[0]}"
TARGET_ROOT="${FIXTURE[1]}"
rm -f "${TARGET_ROOT}/database/manager.py"
if (
    source "${TARGET_PREFLIGHT}" "${TARGET_ROOT}" "${INSTALL_ROOT}"
    preflight_validate_target_package >/dev/null 2>&1
)
then
    fail "incomplete target package passed preflight"
fi

python3 "${ROOT}/tests/update_preflight_sqlite_readonly_test.py"

echo "Update preflight tests passed."
