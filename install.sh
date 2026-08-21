#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_INSTALLER="${ROOT}/install-core.sh"

[[ -x "${CORE_INSTALLER}" ]] || {
    printf '[Capivara][ERRO] Instalador principal ausente: %s\n' "${CORE_INSTALLER}" >&2
    exit 1
}

is_interactive(){ [[ "${DSM_NON_INTERACTIVE:-0}" != "1" && -t 0 && -t 1 ]]; }

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

    if [[ -n "${DSM_DATABASE_DRIVER+x}" ]]; then
        return 0
    fi

    printf '\n==============================================================\n Banco de dados do Controller\n==============================================================\n'
    printf '  1) SQLite      - padrão simples/local\n'
    printf '  2) PostgreSQL  - recomendado para produção e maior escala\n'
    printf '  3) MySQL\n'
    printf '  4) MariaDB\n\n'

    local db_answer
    read -r -p 'Banco [1]: ' db_answer
    case "${db_answer:-1}" in
        1|sqlite) export DSM_DATABASE_DRIVER=sqlite ;;
        2|postgres|postgresql) export DSM_DATABASE_DRIVER=postgresql ;;
        3|mysql) export DSM_DATABASE_DRIVER=mysql ;;
        4|mariadb) export DSM_DATABASE_DRIVER=mariadb ;;
        *) printf '[Capivara][ERRO] Banco inválido: %s\n' "${db_answer}" >&2; exit 1 ;;
    esac

    [[ "${DSM_DATABASE_DRIVER}" != "sqlite" ]] || return 0

    local default_port=3306
    [[ "${DSM_DATABASE_DRIVER}" != "postgresql" ]] || default_port=5432

    read -r -p 'Host do banco: ' DSM_DATABASE_HOST
    read -r -p "Porta [${default_port}]: " DSM_DATABASE_PORT
    DSM_DATABASE_PORT="${DSM_DATABASE_PORT:-${default_port}}"
    read -r -p 'Nome do banco [capivara]: ' DSM_DATABASE_NAME
    DSM_DATABASE_NAME="${DSM_DATABASE_NAME:-capivara}"
    read -r -p 'Usuário do banco: ' DSM_DATABASE_USER
    read -r -p 'Arquivo protegido contendo a senha (opcional): ' DSM_DATABASE_PASSWORD_FILE
    read -r -p 'TLS [preferred]: ' DSM_DATABASE_TLS
    DSM_DATABASE_TLS="${DSM_DATABASE_TLS:-preferred}"

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

    printf '\n==============================================================\n Topologia inicial\n==============================================================\n'
    printf 'Defina a Region e o Datacenter inicial deste Controller.\n'
    printf 'Agents serão vinculados posteriormente a um Datacenter existente.\n\n'

    read -r -p 'ID da Region [default-region]: ' DSM_REGION_ID
    DSM_REGION_ID="${DSM_REGION_ID:-default-region}"
    read -r -p 'Nome da Region [Region Principal]: ' DSM_REGION_NAME
    DSM_REGION_NAME="${DSM_REGION_NAME:-Region Principal}"
    read -r -p 'Código do país [BR]: ' DSM_REGION_COUNTRY_CODE
    DSM_REGION_COUNTRY_CODE="${DSM_REGION_COUNTRY_CODE:-BR}"

    read -r -p 'ID do Datacenter [dc01]: ' DSM_DATACENTER_ID
    DSM_DATACENTER_ID="${DSM_DATACENTER_ID:-dc01}"
    read -r -p 'Nome do Datacenter [Datacenter Principal]: ' DSM_DATACENTER_NAME
    DSM_DATACENTER_NAME="${DSM_DATACENTER_NAME:-Datacenter Principal}"
    read -r -p 'Provider (opcional): ' DSM_DATACENTER_PROVIDER
    read -r -p 'Cidade (opcional): ' DSM_DATACENTER_CITY
    read -r -p "Código do país [${DSM_REGION_COUNTRY_CODE}]: " DSM_DATACENTER_COUNTRY_CODE
    DSM_DATACENTER_COUNTRY_CODE="${DSM_DATACENTER_COUNTRY_CODE:-${DSM_REGION_COUNTRY_CODE}}"

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

select_role_and_database
select_initial_topology
"${CORE_INSTALLER}" "$@"

if [[ " ${*} " != *" --dry-run "* ]]; then
    bootstrap_initial_topology
fi
