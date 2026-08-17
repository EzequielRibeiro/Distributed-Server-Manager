#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="${ROOT}/install.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

fail(){ echo "FAIL: $*" >&2; exit 1; }

source_installer()
{
    # Avoid deriving Windows account names when this test runs under Git Bash.
    id()
    {
        case "${1:-}" in
            -un|-gn) printf 'dsmtest\n' ;;
            *) command id "$@" ;;
        esac
    }
    DSM_SERVICE_USER="dsmtest"
    DSM_SERVICE_GROUP="dsmtest"
    # shellcheck source=../install.sh
    source "${INSTALLER}"
}

(
    source_installer
    DSM_ROOT="${TMP_DIR}/sqlite-root"
    DSM_DATABASE_DRIVER="sqlite3"
    DSM_DATABASE=""
    validate_database_settings
    [[ "${DSM_DATABASE_DRIVER}" == "sqlite" ]] || fail "sqlite3 alias not normalized"
    [[ "${DSM_DATABASE}" == "${DSM_ROOT}/data/capivara.db" ]] || fail "SQLite default path incorrect"
)

(
    source_installer
    DSM_DATABASE_DRIVER="postgres"
    DSM_DATABASE_HOST="db.internal"
    DSM_DATABASE_PORT=""
    DSM_DATABASE_NAME="capivara"
    DSM_DATABASE_USER="capivara"
    DSM_DATABASE_PASSWORD_FILE=""
    DSM_DATABASE_TLS="require"
    validate_database_settings
    [[ "${DSM_DATABASE_DRIVER}" == "postgresql" ]] || fail "PostgreSQL alias not normalized"
    [[ "${DSM_DATABASE_PORT}" == "5432" ]] || fail "PostgreSQL default port incorrect"
)

(
    source_installer
    DSM_DATABASE_DRIVER="mariadb"
    DSM_DATABASE_HOST="db.internal"
    DSM_DATABASE_PORT=""
    DSM_DATABASE_NAME="capivara"
    DSM_DATABASE_USER="capivara"
    DSM_DATABASE_PASSWORD_FILE=""
    DSM_DATABASE_TLS="preferred"
    validate_database_settings
    [[ "${DSM_DATABASE_PORT}" == "3306" ]] || fail "MariaDB default port incorrect"
)

if (
    source_installer
    DSM_DATABASE_DRIVER="postgresql"
    DSM_DATABASE_HOST=""
    DSM_DATABASE_USER="capivara"
    validate_database_settings >/dev/null 2>&1
); then
    fail "network database accepted without host"
fi

if (
    source_installer
    DSM_DATABASE_DRIVER="mysql"
    DSM_DATABASE_HOST="db.internal"
    DSM_DATABASE_USER="capivara"
    DSM_DATABASE_PORT="70000"
    validate_database_settings >/dev/null 2>&1
); then
    fail "invalid database port accepted"
fi

if (
    source_installer
    DSM_DATABASE_DRIVER="postgresql"
    DSM_DATABASE_HOST="db.internal"
    DSM_DATABASE_USER="capivara"
    DSM_DATABASE_TLS="surprise"
    validate_database_settings >/dev/null 2>&1
); then
    fail "invalid TLS mode accepted"
fi

password_file="${TMP_DIR}/database-password"
printf 'secret\n' >"${password_file}"
chmod 600 "${password_file}"

(
    source_installer
    DSM_DATABASE_DRIVER="mysql"
    DSM_DATABASE_HOST="db.internal"
    DSM_DATABASE_USER="capivara"
    DSM_DATABASE_PASSWORD_FILE="${password_file}"
    validate_database_settings
)

chmod 644 "${password_file}"
if [[ "$(uname -s)" == "Linux" ]]
then
    if (
        source_installer
        DSM_DATABASE_DRIVER="mysql"
        DSM_DATABASE_HOST="db.internal"
        DSM_DATABASE_USER="capivara"
        DSM_DATABASE_PASSWORD_FILE="${password_file}"
        validate_database_settings >/dev/null 2>&1
    ); then
        fail "insecure password file accepted"
    fi
fi

(
    source_installer
    DSM_ROOT="${TMP_DIR}/manager-root"
    DSM_DATABASE_DRIVER="postgresql"
    DSM_DATABASE_HOST="db.internal"
    DSM_DATABASE_PORT="5432"
    DSM_DATABASE_NAME="capivara"
    DSM_DATABASE_USER="capivara"
    DSM_DATABASE_PASSWORD_FILE="/run/secrets/database"
    DSM_DATABASE_TLS="require"
    python3()
    {
        printf '%s\n' "$@" >"${TMP_DIR}/manager-arguments"
    }
    run_database_manager check
    grep -Fxq -- '--driver' "${TMP_DIR}/manager-arguments" || fail "manager driver argument missing"
    grep -Fxq -- 'postgresql' "${TMP_DIR}/manager-arguments" || fail "manager driver value missing"
    grep -Fxq -- '--password-file' "${TMP_DIR}/manager-arguments" || fail "password-file argument missing"
    ! grep -Fxq 'secret' "${TMP_DIR}/manager-arguments" || fail "password leaked to manager arguments"
)

(
    source_installer
    chown(){ :; }
    chmod(){ :; }
    DSM_ROOT="${TMP_DIR}/network-root"
    DSM_SERVICE_USER="dsmtest"
    DSM_SERVICE_GROUP="dsmtest"
    DSM_SERVICE_HOME="/srv/dsmtest"
    DSM_DATABASE_DRIVER="mariadb"
    DSM_DATABASE=""
    DSM_DATABASE_HOST="db.internal"
    DSM_DATABASE_PORT="3306"
    DSM_DATABASE_NAME="capivara"
    DSM_DATABASE_USER="capivara"
    DSM_DATABASE_PASSWORD_FILE="/run/secrets/database"
    DSM_DATABASE_TLS="required"
    mkdir -p "${DSM_ROOT}/config"
    cp "${ROOT}/config/dsm.conf" "${DSM_ROOT}/config/dsm.conf"
    cp "${ROOT}/version" "${DSM_ROOT}/version"
    write_dsm_config >/dev/null
    config="${DSM_ROOT}/config/dsm.conf"
    grep -q '^DSM_DATABASE_DRIVER="mariadb"$' "${config}" || fail "MariaDB driver not written"
    grep -q '^DSM_DATABASE_HOST="db.internal"$' "${config}" || fail "database host not written"
    grep -q '^DSM_DATABASE_PASSWORD_FILE="/run/secrets/database"$' "${config}" || fail "password file not written"
    ! grep -Fq 'secret-value' "${config}" || fail "database password leaked to config"
)

(
    source_installer
    DSM_ROOT="${TMP_DIR}/dry-run-root"
    DSM_DATABASE_DRIVER="sqlite"
    DSM_DATABASE="${DSM_ROOT}/data/capivara.db"
    DRY_RUN=1
    initialize_database >/dev/null
    write_dsm_config >/dev/null
    [[ ! -e "${DSM_ROOT}" ]] || fail "dry-run changed the target filesystem"
)

echo "Install database tests passed."
