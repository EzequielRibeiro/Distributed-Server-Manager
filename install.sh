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

    # Agent puro mantém SQLite local por padrão e não recebe perguntas de
    # credenciais de um banco central que não administra.
    if [[ "${DSM_NODE_ROLE}" == "agent" ]]; then
        export DSM_DATABASE_DRIVER="${DSM_DATABASE_DRIVER:-sqlite}"
        return 0
    fi

    # Respeita configuração explícita fornecida por automação/administrador.
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

select_role_and_database
exec "${CORE_INSTALLER}" "$@"
