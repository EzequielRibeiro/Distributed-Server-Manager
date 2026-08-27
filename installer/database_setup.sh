#!/usr/bin/env bash
# Database provisioning and pre-persistence validation for install-core.sh.

database_host_is_local()
{
    case "${DSM_DATABASE_HOST,,}" in localhost|127.0.0.1|::1) return 0;; *) return 1;; esac
}

database_supported_apt_host()
{
    [[ -r /etc/os-release ]] || return 1
    local id like
    id="$(. /etc/os-release; printf '%s' "${ID:-}")"
    like="$(. /etc/os-release; printf '%s' "${ID_LIKE:-}")"
    [[ "${id} ${like}" == *debian* || "${id}" == ubuntu ]]
}

install_database_packages()
{
    command -v apt-get >/dev/null 2>&1 && database_supported_apt_host \
        || die "Instalação automática de banco local requer Ubuntu/Debian suportado."
    local -a packages=()
    case "${DSM_DATABASE_DRIVER}" in
        postgresql)
            packages=(python3-psycopg)
            database_host_is_local && packages+=(postgresql postgresql-contrib)
            ;;
        mysql)
            packages=(python3-mysql.connector)
            database_host_is_local && packages+=(mysql-server)
            ;;
        mariadb)
            packages=(python3-mysql.connector)
            database_host_is_local && packages+=(mariadb-server)
            ;;
    esac
    DEBIAN_FRONTEND=noninteractive apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
}

ensure_database_dependencies()
{
    case "${DSM_DATABASE_DRIVER}" in
        sqlite)
            python3 -c 'import sqlite3' >/dev/null 2>&1 \
                || die "Driver Python sqlite3 indisponível."
            ;;
        postgresql)
            if ! python3 -c 'import psycopg' >/dev/null 2>&1; then
                install_database_packages
            fi
            if database_host_is_local \
                && { ! command -v psql >/dev/null 2>&1 \
                    || ! dpkg-query -W postgresql >/dev/null 2>&1; }; then
                install_database_packages
            fi
            ;;
        mysql|mariadb)
            if ! python3 -c 'import mysql.connector' >/dev/null 2>&1; then
                install_database_packages
            fi
            local server_package=mysql-server
            [[ "${DSM_DATABASE_DRIVER}" == mariadb ]] && server_package=mariadb-server
            if database_host_is_local \
                && { ! command -v mysql >/dev/null 2>&1 \
                    || ! dpkg-query -W "${server_package}" >/dev/null 2>&1; }; then
                install_database_packages
            fi
            ;;
    esac
}

start_local_database_service()
{
    database_host_is_local || return 0
    local service
    case "${DSM_DATABASE_DRIVER}" in
        postgresql) service=postgresql;;
        mysql) service=mysql;;
        mariadb) service=mariadb;;
        *) return 0;;
    esac
    systemctl enable --now "${service}" >/dev/null \
        || die "Não foi possível habilitar/iniciar ${service}."
}

sql_quote_literal()
{
    # SQL identifiers are separately restricted; double quotes are escaped here.
    printf '%s' "$1" | sed "s/'/''/g"
}

prepare_local_postgresql()
{
    local password escaped
    password="$(<"${DSM_DATABASE_PASSWORD_FILE}")"
    escaped="$(sql_quote_literal "${password}")"
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 postgres >/dev/null <<SQL
DO \$body\$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${DSM_DATABASE_USER}') THEN
  CREATE ROLE ${DSM_DATABASE_USER} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '${escaped}';
 END IF;
END \$body\$;
-- Reconcile the existing local role with the configured secret as well.
-- This keeps reinstalls/idempotent runs from retaining a stale PostgreSQL password.
ALTER ROLE ${DSM_DATABASE_USER} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '${escaped}';
SELECT 'CREATE DATABASE ${DSM_DATABASE_NAME} OWNER ${DSM_DATABASE_USER}'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='${DSM_DATABASE_NAME}')\gexec
GRANT ALL PRIVILEGES ON DATABASE ${DSM_DATABASE_NAME} TO ${DSM_DATABASE_USER};
SQL
    unset password escaped
}

prepare_local_mysql()
{
    local password escaped hostpart
    password="$(<"${DSM_DATABASE_PASSWORD_FILE}")"
    escaped="$(sql_quote_literal "${password}")"
    hostpart=localhost
    mysql --protocol=socket -uroot >/dev/null <<SQL
CREATE DATABASE IF NOT EXISTS \`${DSM_DATABASE_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DSM_DATABASE_USER}'@'${hostpart}' IDENTIFIED BY '${escaped}';
GRANT ALL PRIVILEGES ON \`${DSM_DATABASE_NAME}\`.* TO '${DSM_DATABASE_USER}'@'${hostpart}';
FLUSH PRIVILEGES;
SQL
    unset password escaped
}

prepare_local_database()
{
    database_host_is_local || return 0
    case "${DSM_DATABASE_DRIVER}" in
        postgresql) prepare_local_postgresql;;
        mysql|mariadb) prepare_local_mysql;;
    esac
}

check_remote_endpoint()
{
    database_host_is_local && return 0
    getent ahosts "${DSM_DATABASE_HOST}" >/dev/null 2>&1 \
        || die "DNS não resolveu o host remoto ${DSM_DATABASE_HOST}."
    python3 - "${DSM_DATABASE_HOST}" "${DSM_DATABASE_PORT}" <<'PY' \
        || die "TCP remoto indisponível em ${DSM_DATABASE_HOST}:${DSM_DATABASE_PORT}."
import socket, sys
with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5): pass
PY
}

check_sqlite_operational()
{
    python3 - <<'PY' || die "SQLite falhou no teste de transação/integridade."
import sqlite3, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as d:
    db = Path(d) / "preflight.db"
    con = sqlite3.connect(db)
    con.execute("create table probe(value integer)")
    con.execute("begin"); con.execute("insert into probe values (1)"); con.rollback()
    assert con.execute("pragma integrity_check").fetchone()[0] == "ok"
    con.close()
PY
}

prevalidate_database()
{
    section "Validação operacional do banco"
    if (( DRY_RUN )); then
        DATABASE_CONNECTION_STATUS="não testada (dry-run)"
        return 0
    fi
    if [[ "${DSM_DATABASE_DRIVER}" == sqlite ]]; then
        check_sqlite_operational
    else
        ensure_database_dependencies
        start_local_database_service
        prepare_local_database
        check_remote_endpoint
        run_source_database_manager check >/dev/null \
            || die "Conexão real ao banco falhou; nenhuma instalação do Capivara foi iniciada."
        # A conexão isolada não basta: um banco parcialmente inicializado
        # precisa ser recusado antes de criar conta, /opt/dsm ou systemd.
        # Em banco vazio, init aplica o baseline consolidado; em banco já
        # inicializado, ele valida a presença das tabelas obrigatórias.
        run_source_database_manager init >/dev/null \
            || die "Schema do banco ausente, parcial ou incompatível; nenhuma instalação do Capivara foi iniciada."
    fi
    DATABASE_CONNECTION_STATUS=operacional
    log "Banco validado com os parâmetros exatos informados."
}

run_source_database_manager()
{
    local saved_root="${DSM_ROOT}"
    DSM_ROOT="${DSM_SOURCE}"
    run_database_manager "$@"
    DSM_ROOT="${saved_root}"
}

transfer_database_secret_ownership()
{
    [[ "${DSM_DATABASE_DRIVER}" != sqlite ]] || return 0
    chown "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "$(dirname "${DSM_DATABASE_PASSWORD_FILE}")" "${DSM_DATABASE_PASSWORD_FILE}"
    chmod 700 "$(dirname "${DSM_DATABASE_PASSWORD_FILE}")"
    chmod 600 "${DSM_DATABASE_PASSWORD_FILE}"
}
