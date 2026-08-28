#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_INSTALLER="${ROOT}/install-core.sh"
WEB_TRANSPORT_HELPER="${ROOT}/installer/web_transport.sh"

[[ -x "${CORE_INSTALLER}" ]] || {
    printf '[Capivara][ERRO] Instalador principal ausente: %s\n' "${CORE_INSTALLER}" >&2
    exit 1
}
[[ -f "${WEB_TRANSPORT_HELPER}" ]] || {
    printf '[Capivara][ERRO] Helper de transporte ausente: %s\n' "${WEB_TRANSPORT_HELPER}" >&2
    exit 1
}
# shellcheck source=installer/web_transport.sh
source "${WEB_TRANSPORT_HELPER}"

is_interactive(){ [[ "${DSM_NON_INTERACTIVE:-0}" != "1" && -t 0 && -t 1 ]]; }

create_database_password_secret(){
    local secret_path="${DSM_DATABASE_PASSWORD_FILE:-/etc/capivara/secrets/database-password}"
    local password confirmation
    printf '\n==============================================================\n Credencial do banco de dados\n==============================================================\n'
    printf 'O Capivara criará um arquivo protegido para a senha do banco.\n'
    printf 'A senha não aparecerá na tela, histórico ou logs; o Controller\n'
    printf 'usará esse arquivo exclusivamente para autenticação.\nArquivo: %s\n\n' "${secret_path}"
    while true; do
        IFS= read -r -s -p 'Senha do usuário do banco: ' password; printf '\n'
        IFS= read -r -s -p 'Confirme a senha: ' confirmation; printf '\n'
        [[ -n "${password}" ]] || { printf '[Capivara][ERRO] A senha não pode ser vazia.\n' >&2; continue; }
        [[ "${password}" == "${confirmation}" ]] && break
        printf '[Capivara][ERRO] As senhas informadas não coincidem.\n' >&2
    done
    install -d -m 700 -o root -g root "$(dirname "${secret_path}")"
    (umask 077; printf '%s' "${password}" >"${secret_path}")
    chown root:root "${secret_path}"
    chmod 600 "${secret_path}"
    unset password confirmation
    export DSM_DATABASE_PASSWORD_FILE="${secret_path}"
}

select_role_and_database(){
    is_interactive || return 0

    if [[ -z "${DSM_NODE_ROLE:-}" ]]; then
        printf '\n==============================================================\n Perfil deste node\n==============================================================\n'
        printf '  1) controller  - Controlador central\n'
        printf '  2) agent       - Executa instâncias de jogos\n'
        printf '  3) hybrid      - Controller e Agent na mesma máquina\n\n'
        local role_answer
        read -r -p 'Papel [2]: ' role_answer
        case "${role_answer:-2}" in
            1|controller) export DSM_NODE_ROLE=controller ;;
            2|agent) export DSM_NODE_ROLE=agent ;;
            3|hybrid) export DSM_NODE_ROLE=hybrid ;;
            *) printf '[Capivara][ERRO] Papel inválido: %s\n' "${role_answer}" >&2; exit 1 ;;
        esac
    fi

    if [[ "${DSM_NODE_ROLE}" == "agent" ]]; then
        export DSM_DATABASE_DRIVER="${DSM_DATABASE_DRIVER:-sqlite}"
        return 0
    fi

    if [[ -z "${DSM_DATABASE_DRIVER+x}" ]]; then
        printf '\n==============================================================\n Banco de dados do Controller\n==============================================================\n'
        printf '  1) SQLite      - padrão simples/local\n  2) PostgreSQL  - recomendado para produção\n  3) MySQL\n  4) MariaDB\n\n'
        local db_answer
        read -r -p 'Banco [1]: ' db_answer
        case "${db_answer:-1}" in
            1|sqlite) export DSM_DATABASE_DRIVER=sqlite ;;
            2|postgres|postgresql) export DSM_DATABASE_DRIVER=postgresql ;;
            3|mysql) export DSM_DATABASE_DRIVER=mysql ;;
            4|mariadb) export DSM_DATABASE_DRIVER=mariadb ;;
            *) printf '[Capivara][ERRO] Banco inválido: %s\n' "${db_answer}" >&2; exit 1 ;;
        esac
    fi

    [[ "${DSM_DATABASE_DRIVER}" != "sqlite" ]] || return 0

    local default_port=3306
    [[ "${DSM_DATABASE_DRIVER}" != "postgresql" ]] || default_port=5432

    read -r -p 'Host do banco [localhost]: ' DSM_DATABASE_HOST
    DSM_DATABASE_HOST="${DSM_DATABASE_HOST:-localhost}"
    read -r -p "Porta [${default_port}]: " DSM_DATABASE_PORT
    DSM_DATABASE_PORT="${DSM_DATABASE_PORT:-${default_port}}"
    read -r -p 'Nome do banco [capivara]: ' DSM_DATABASE_NAME
    DSM_DATABASE_NAME="${DSM_DATABASE_NAME:-capivara}"
    read -r -p 'Usuário dedicado do banco [capivara]: ' DSM_DATABASE_USER
    DSM_DATABASE_USER="${DSM_DATABASE_USER:-capivara}"
    read -r -p 'TLS [preferred]: ' DSM_DATABASE_TLS
    DSM_DATABASE_TLS="${DSM_DATABASE_TLS:-preferred}"
    create_database_password_secret

    [[ -n "${DSM_DATABASE_HOST}" ]] || { printf '[Capivara][ERRO] Host do banco é obrigatório.\n' >&2; exit 1; }
    [[ -n "${DSM_DATABASE_USER}" ]] || { printf '[Capivara][ERRO] Usuário do banco é obrigatório.\n' >&2; exit 1; }

    export DSM_DATABASE_HOST DSM_DATABASE_PORT DSM_DATABASE_NAME
    export DSM_DATABASE_USER DSM_DATABASE_PASSWORD_FILE DSM_DATABASE_TLS
}

select_initial_topology(){
    [[ "${DSM_NODE_ROLE:-}" == "controller" || "${DSM_NODE_ROLE:-}" == "hybrid" ]] || return 0

    if [[ -n "${DSM_REGION_ID:-}" && -n "${DSM_DATACENTER_ID:-}" ]]; then
        return 0
    fi

    is_interactive || return 0

    DSM_REGION_ID="${DSM_REGION_ID:-default-region}"
    DSM_REGION_NAME="${DSM_REGION_NAME:-Region Principal}"
    DSM_REGION_COUNTRY_CODE="${DSM_REGION_COUNTRY_CODE:-BR}"
    DSM_DATACENTER_ID="${DSM_DATACENTER_ID:-dc01}"
    DSM_DATACENTER_NAME="${DSM_DATACENTER_NAME:-Datacenter Principal}"
    DSM_DATACENTER_PROVIDER="${DSM_DATACENTER_PROVIDER:-}"
    DSM_DATACENTER_CITY="${DSM_DATACENTER_CITY:-}"
    DSM_DATACENTER_COUNTRY_CODE="${DSM_DATACENTER_COUNTRY_CODE:-}"

    local value confirmation
    while true; do
        printf '\n==============================================================\n Topologia inicial\n==============================================================\n'
        printf 'Defina a Region e o Datacenter inicial deste Controller.\n'
        printf 'Agents serão vinculados posteriormente a um Datacenter existente.\n\n'

        read -r -p "ID da Region [${DSM_REGION_ID}]: " value
        DSM_REGION_ID="${value:-${DSM_REGION_ID}}"
        read -r -p "Nome da Region [${DSM_REGION_NAME}]: " value
        DSM_REGION_NAME="${value:-${DSM_REGION_NAME}}"
        read -r -p "Código do país [${DSM_REGION_COUNTRY_CODE}]: " value
        DSM_REGION_COUNTRY_CODE="${value:-${DSM_REGION_COUNTRY_CODE}}"

        read -r -p "ID do Datacenter [${DSM_DATACENTER_ID}]: " value
        DSM_DATACENTER_ID="${value:-${DSM_DATACENTER_ID}}"
        read -r -p "Nome do Datacenter [${DSM_DATACENTER_NAME}]: " value
        DSM_DATACENTER_NAME="${value:-${DSM_DATACENTER_NAME}}"
        read -r -p "Provider [${DSM_DATACENTER_PROVIDER:-não informado}]: " value
        DSM_DATACENTER_PROVIDER="${value:-${DSM_DATACENTER_PROVIDER}}"
        read -r -p "Cidade [${DSM_DATACENTER_CITY:-não informada}]: " value
        DSM_DATACENTER_CITY="${value:-${DSM_DATACENTER_CITY}}"
        DSM_DATACENTER_COUNTRY_CODE="${DSM_DATACENTER_COUNTRY_CODE:-${DSM_REGION_COUNTRY_CODE}}"
        read -r -p "Código do país [${DSM_DATACENTER_COUNTRY_CODE}]: " value
        DSM_DATACENTER_COUNTRY_CODE="${value:-${DSM_DATACENTER_COUNTRY_CODE}}"

        printf '\n==============================================================\n Revisão da topologia inicial\n==============================================================\n'
        printf 'Region ID          : %s\n' "${DSM_REGION_ID}"
        printf 'Region nome        : %s\n' "${DSM_REGION_NAME}"
        printf 'Region país        : %s\n' "${DSM_REGION_COUNTRY_CODE}"
        printf 'Datacenter ID      : %s\n' "${DSM_DATACENTER_ID}"
        printf 'Datacenter nome    : %s\n' "${DSM_DATACENTER_NAME}"
        printf 'Provider           : %s\n' "${DSM_DATACENTER_PROVIDER:-não informado}"
        printf 'Cidade             : %s\n' "${DSM_DATACENTER_CITY:-não informada}"
        printf 'Datacenter país    : %s\n' "${DSM_DATACENTER_COUNTRY_CODE}"
        read -r -p 'Os dados estão corretos? [S/n]: ' confirmation
        case "${confirmation:-s}" in
            s|S|sim|SIM|y|Y|yes|YES) break ;;
            *) printf '\nRevise os dados da topologia. Enter mantém o valor atual.\n' ;;
        esac
    done

    export DSM_REGION_ID DSM_REGION_NAME DSM_REGION_COUNTRY_CODE
    export DSM_DATACENTER_ID DSM_DATACENTER_NAME DSM_DATACENTER_PROVIDER
    export DSM_DATACENTER_CITY DSM_DATACENTER_COUNTRY_CODE
}

bootstrap_initial_topology(){
    [[ "${DSM_NODE_ROLE:-}" == "controller" || "${DSM_NODE_ROLE:-}" == "hybrid" ]] || return 0
    [[ -n "${DSM_REGION_ID:-}" && -n "${DSM_DATACENTER_ID:-}" ]] || return 0
    [[ "${1:-}" != "--dry-run" ]] || return 0

    local helper="${DSM_ROOT:-/opt/dsm}/database/topology_bootstrap.py"
    [[ -f "${helper}" ]] || {
        printf '[Capivara][ERRO] Bootstrap de topologia ausente: %s\n' "${helper}" >&2
        return 1
    }

    python3 "${helper}" --root "${DSM_ROOT:-/opt/dsm}" \
        --region-id "${DSM_REGION_ID}" \
        --region-name "${DSM_REGION_NAME:-${DSM_REGION_ID}}" \
        --region-country-code "${DSM_REGION_COUNTRY_CODE:-}" \
        --datacenter-id "${DSM_DATACENTER_ID}" \
        --datacenter-name "${DSM_DATACENTER_NAME:-${DSM_DATACENTER_ID}}" \
        --datacenter-provider "${DSM_DATACENTER_PROVIDER:-}" \
        --datacenter-city "${DSM_DATACENTER_CITY:-}" \
        --datacenter-country-code "${DSM_DATACENTER_COUNTRY_CODE:-${DSM_REGION_COUNTRY_CODE:-}}"
}

retire_obsolete_systemd_units(){
    [[ " ${*} " != *" --dry-run "* ]] || return 0
    [[ "${EUID}" -eq 0 ]] || return 0
    command -v systemctl >/dev/null 2>&1 || return 0

    local systemd_dir="${SYSTEMD_DIR:-/etc/systemd/system}"
    local unit
    local -a retired_units=(
        dsm-notification-engine.timer
        dsm-notification-center.timer
        dsm-backup-worker.service
        dsm-events-worker.service
        dsm-metrics-worker.service
        dsm-mods-worker.service
        dsm-server-worker.service
    )

    for unit in "${retired_units[@]}"; do
        systemctl disable --now "${unit}" >/dev/null 2>&1 || true
        rm -f -- "${systemd_dir}/${unit}"
    done

    systemctl daemon-reload >/dev/null 2>&1 || true
}

resolve_installed_service_account(){
    [[ " ${*} " != *" --dry-run "* ]] || return 0

    local config="${DSM_ROOT:-/opt/dsm}/config/dsm.conf"
    local installed_user=""
    local installed_group=""

    if [[ -f "${config}" ]]; then
        installed_user="$(sed -n 's/^DSM_USER="\([^"]*\)"$/\1/p' "${config}" | tail -n 1)"
        installed_group="$(sed -n 's/^DSM_GROUP="\([^"]*\)"$/\1/p' "${config}" | tail -n 1)"
    fi

    DSM_SERVICE_USER="${installed_user:-${DSM_SERVICE_USER:-}}"
    DSM_SERVICE_GROUP="${installed_group:-${DSM_SERVICE_GROUP:-}}"

    [[ -n "${DSM_SERVICE_USER}" && -n "${DSM_SERVICE_GROUP}" ]] || {
        printf '[Capivara][ERRO] Não foi possível resolver a conta de serviço instalada.\n' >&2
        return 1
    }

    export DSM_SERVICE_USER DSM_SERVICE_GROUP
}

reconcile_managed_tls_permissions(){
    [[ "${DSM_WEB_SCHEME:-http}" == https ]] || return 0
    [[ " ${*} " != *" --dry-run "* ]] || return 0

    case "${DSM_TLS_CERT_MODE:-}" in
        letsencrypt|selfsigned)
            local tls_dir="$(dirname "${DSM_TLS_KEY_FILE}")"
            install -d -m 0750 -o root -g "${DSM_SERVICE_GROUP}" "${tls_dir}"

            if [[ -f "${DSM_TLS_CERT_FILE}" ]]; then
                chown root:"${DSM_SERVICE_GROUP}" "${DSM_TLS_CERT_FILE}"
                chmod 0640 "${DSM_TLS_CERT_FILE}"
            fi

            if [[ -f "${DSM_TLS_KEY_FILE}" ]]; then
                chown root:"${DSM_SERVICE_GROUP}" "${DSM_TLS_KEY_FILE}"
                chmod 0640 "${DSM_TLS_KEY_FILE}"
            fi
            ;;
    esac
}

select_role_and_database
select_web_transport
select_initial_topology
prepare_web_transport_certificate "$@"
retire_obsolete_systemd_units "$@"
"${CORE_INSTALLER}" "$@"
resolve_installed_service_account "$@"
reconcile_managed_tls_permissions "$@"
persist_web_transport_config "$@"
retire_obsolete_systemd_units "$@"

if [[ " ${*} " != *" --dry-run "* ]]; then
    bootstrap_initial_topology
fi
