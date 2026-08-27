#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_INSTALLER="${ROOT}/install-core.sh"
ENGINE="${ROOT}/install-core-engine.sh"
LEGACY_TEST="${ROOT}/tests/install_manager_legacy_test.sh"
fail(){ echo "FAIL: $*" >&2; exit 1; }

# Run the historical suite against the unchanged implementation body. The
# public entrypoint is restored immediately afterwards and is tested below.
TMP_WRAPPER="$(mktemp)"
cp "${CORE_INSTALLER}" "${TMP_WRAPPER}"
restore_wrapper(){ cp "${TMP_WRAPPER}" "${CORE_INSTALLER}"; chmod +x "${CORE_INSTALLER}"; rm -f "${TMP_WRAPPER}"; }
trap restore_wrapper EXIT
cp "${ENGINE}" "${CORE_INSTALLER}"
chmod +x "${CORE_INSTALLER}"
bash "${LEGACY_TEST}"
restore_wrapper
trap - EXIT

bash -n "${CORE_INSTALLER}"

# A role already selected by install.sh must not be shown a second time.
PROFILE_OUTPUT="$({
    source "${CORE_INSTALLER}"
    is_interactive(){ return 0; }
    DSM_NODE_ROLE=controller
    DSM_SERVICE_USER=capivara
    DSM_SERVICE_GROUP=capivara
    select_installation_profile
} 2>&1)"
if grep -Fq 'Perfil deste node' <<<"${PROFILE_OUTPUT}"; then
    fail "preselected node role is displayed a second time"
fi
if grep -Fq 'Papéis disponíveis' <<<"${PROFILE_OUTPUT}"; then
    fail "preselected node role catalogue is displayed a second time"
fi

# If only the role is preselected, the remaining prompt is explicitly the
# service-account stage instead of another role-selection stage.
ACCOUNT_OUTPUT="$({
    source "${CORE_INSTALLER}"
    is_interactive(){ return 0; }
    CURRENT_MACHINE_USER=capivara
    CURRENT_MACHINE_GROUP=capivara
    DSM_NODE_ROLE=controller
    DSM_SERVICE_USER=''
    DSM_SERVICE_GROUP=''
    select_installation_profile <<< $'\n\n'
} 2>&1)"
grep -Fq 'Conta de serviço' <<<"${ACCOUNT_OUTPUT}" \
    || fail "preselected role does not transition to service-account stage"
if grep -Fq 'Papéis disponíveis' <<<"${ACCOUNT_OUTPUT}"; then
    fail "service-account stage repeats role catalogue"
fi

# The database-manager failure code must survive DSM_ROOT restoration.
(
    source "${CORE_INSTALLER}"
    DSM_ROOT='/saved/root'
    DSM_SOURCE='/source/root'
    run_database_manager(){ return 23; }
    set +e
    run_source_database_manager check
    status=$?
    set -e
    [[ "${status}" -eq 23 ]] || fail "database manager failure was masked: ${status}"
    [[ "${DSM_ROOT}" == '/saved/root' ]] || fail "DSM_ROOT was not restored after database failure"
)

# Authentication/manager failure must abort prevalidation and must never emit
# the success message that previously followed the JSON DatabaseError.
set +e
DB_OUTPUT="$({
    source "${CORE_INSTALLER}"
    DRY_RUN=0
    DSM_DATABASE_DRIVER=postgresql
    DSM_DATABASE_HOST=127.0.0.1
    DSM_DATABASE_PORT=5432
    DSM_DATABASE_NAME=capivara
    DSM_DATABASE_USER=capivara
    DSM_DATABASE_PASSWORD_FILE=/tmp/not-used
    DSM_SOURCE=/source/root
    DSM_ROOT=/saved/root
    ensure_database_dependencies(){ :; }
    start_local_database_service(){ :; }
    prepare_local_database(){ :; }
    check_remote_endpoint(){ :; }
    run_database_manager(){ printf '%s\n' '{"schema_version":1,"kind":"DatabaseError","error":"password authentication failed"}' >&2; return 2; }
    prevalidate_database
} 2>&1)"
DB_STATUS=$?
set -e
[[ "${DB_STATUS}" -ne 0 ]] || fail "database authentication failure did not abort prevalidation"
grep -Fq 'Conexão real ao banco falhou' <<<"${DB_OUTPUT}" \
    || fail "database authentication failure did not produce blocking installer error"
if grep -Fq 'Banco validado com os parâmetros exatos informados.' <<<"${DB_OUTPUT}"; then
    fail "database authentication failure still produced success message"
fi

echo "Installer preflight regression tests passed."
