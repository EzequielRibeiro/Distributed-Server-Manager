#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
# Installation Manager
# =============================================================

set -Eeuo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_SOURCE="${INSTALLER_DIR}"

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_BIN="${DSM_ROOT}/bin/dsm"
CAP_BIN="${DSM_ROOT}/bin/cap"
DSM_LINK="${DSM_LINK:-/usr/local/bin/dsm}"
CAP_LINK="${CAP_LINK:-/usr/local/bin/cap}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

CAPIVARA_GITHUB_REPO="${CAPIVARA_GITHUB_REPO:-EzequielRibeiro/Distributed-Server-Manager}"
CAPIVARA_GITHUB_API="${CAPIVARA_GITHUB_API:-https://api.github.com}"
CAPIVARA_RELEASE_TAG="${CAPIVARA_RELEASE_TAG:-latest}"

GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

CURRENT_MACHINE_USER="${SUDO_USER:-$(id -un)}"
CURRENT_MACHINE_GROUP="$(id -gn "${CURRENT_MACHINE_USER}")"

DSM_SERVICE_USER="${DSM_SERVICE_USER:-}"
DSM_SERVICE_GROUP="${DSM_SERVICE_GROUP:-}"
DSM_SERVICE_HOME="${DSM_SERVICE_HOME:-}"
DSM_NODE_ROLE="${DSM_NODE_ROLE:-}"

INSTALL_MODE="${DSM_INSTALL_SOURCE:-remote}"
INSTALL_MODE_EXPLICIT=0

[[ -n "${DSM_INSTALL_SOURCE:-}" ]] \
    && INSTALL_MODE_EXPLICIT=1

INSTALL_STEAMCMD="${DSM_INSTALL_STEAMCMD:-auto}"
INSTALL_SYSTEMD="${DSM_INSTALL_SYSTEMD:-auto}"
STEAMCMD_ROOT="${STEAMCMD_ROOT:-/opt/steamcmd}"

DSM_DATABASE_DRIVER="${DSM_DATABASE_DRIVER:-sqlite}"
DSM_DATABASE="${DSM_DATABASE:-}"
DSM_DATABASE_HOST="${DSM_DATABASE_HOST:-}"
DSM_DATABASE_PORT="${DSM_DATABASE_PORT:-}"
DSM_DATABASE_NAME="${DSM_DATABASE_NAME:-capivara}"
DSM_DATABASE_USER="${DSM_DATABASE_USER:-}"
DSM_DATABASE_PASSWORD_FILE="${DSM_DATABASE_PASSWORD_FILE:-}"
DSM_DATABASE_TLS="${DSM_DATABASE_TLS:-preferred}"

NON_INTERACTIVE="${DSM_NON_INTERACTIVE:-0}"

ALLOW_REINSTALL=0
DRY_RUN=0
SYSTEMD_ACTIVE=0

BOOTSTRAP_TMP=""
RELEASE_VERSION=""
RELEASE_ARCHIVE=""
RELEASE_MANIFEST=""
RELEASE_ROOT=""

# =============================================================
# Output
# =============================================================

log()
{
    printf '[Capivara] %s\n' "$*"
}

warn()
{
    printf '[Capivara][AVISO] %s\n' "$*" >&2
}

die()
{
    printf '[Capivara][ERRO] %s\n' "$*" >&2
    exit 1
}

section()
{
    printf '\n'
    printf '==============================================================\n'
    printf ' %s\n' "$1"
    printf '==============================================================\n'
}

explain()
{
    printf '\n[O que vai acontecer]\n%s\n' "$1"
}

run()
{
    if (( DRY_RUN ))
    then
        printf '[DRY-RUN]'
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi

    "$@"
}

cleanup()
{
    if [[ -n "${BOOTSTRAP_TMP}" \
        && -d "${BOOTSTRAP_TMP}" \
        && "${BOOTSTRAP_TMP}" == /tmp/capivara-installer.* ]]
    then
        rm -rf -- "${BOOTSTRAP_TMP}"
    fi
}

trap cleanup EXIT

# =============================================================
# Help
# =============================================================

usage()
{
    cat <<'EOF_USAGE'
Uso:

  sudo ./install.sh
  sudo ./install.sh --local
  sudo ./install.sh --remote
  sudo ./install.sh --version TAG
  sudo ./install.sh --reinstall
  ./install.sh --dry-run [--local|--remote]

Opções:

  --local
      Usa o checkout local como origem.

  --remote
      Instala uma GitHub Release oficial.

  --version TAG
      Instala uma release específica.

  --reinstall
      Permite reinstalação explícita sobre uma instalação existente.
      Configurações e dados persistentes continuam protegidos.

  --dry-run
      Valida o plano sem modificar o sistema.

Variáveis:

  DSM_NODE_ROLE=controller|agent|hybrid
  DSM_SERVICE_USER=usuario
  DSM_SERVICE_GROUP=grupo
  DSM_INSTALL_STEAMCMD=auto|1|0
  DSM_DATABASE_DRIVER=sqlite|postgresql|mysql|mariadb
  DSM_DATABASE=/caminho/capivara.db
  DSM_DATABASE_HOST=host
  DSM_DATABASE_PORT=porta
  DSM_DATABASE_NAME=capivara
  DSM_DATABASE_USER=usuario
  DSM_DATABASE_PASSWORD_FILE=/run/secrets/dsm-database
  DSM_DATABASE_TLS=preferred|required|verify-ca|verify-full|disable
  GH_TOKEN=token
EOF_USAGE
}

# =============================================================
# CLI
# =============================================================

parse_args()
{
    while (( $# ))
    do
        case "$1" in
            --local)
                INSTALL_MODE="local"
                INSTALL_MODE_EXPLICIT=1
                shift
                ;;

            --remote)
                INSTALL_MODE="remote"
                INSTALL_MODE_EXPLICIT=1
                shift
                ;;

            --version)
                [[ $# -ge 2 ]] \
                    || die "--version requer uma tag."

                INSTALL_MODE="remote"
                INSTALL_MODE_EXPLICIT=1
                CAPIVARA_RELEASE_TAG="$2"

                shift 2
                ;;

            --reinstall)
                ALLOW_REINSTALL=1
                shift
                ;;

            --dry-run)
                DRY_RUN=1
                shift
                ;;

            --help|-h)
                usage
                exit 0
                ;;

            *)
                die "Opção desconhecida: $1"
                ;;
        esac
    done

    case "${INSTALL_MODE}" in
        local|remote)
            ;;
        *)
            die "Origem inválida: ${INSTALL_MODE}"
            ;;
    esac
}

require_root()
{
    (( DRY_RUN )) && return 0

    [[ "${EUID}" -eq 0 ]] \
        || die "Execute como root: sudo ./install.sh"
}

is_interactive()
{
    [[ "${NON_INTERACTIVE}" != "1" && -t 0 && -t 1 ]]
}

# =============================================================
# Bootstrap security libraries
# =============================================================

bootstrap_security()
{
    local semver_lib="${INSTALLER_DIR}/core/semver.sh"
    local archive_lib="${INSTALLER_DIR}/core/archive_security.sh"
    local archive_inspector="${INSTALLER_DIR}/core/archive_inspector.py"

    [[ -f "${semver_lib}" ]] \
        || die "Biblioteca SemVer ausente: ${semver_lib}"

    [[ -f "${archive_lib}" ]] \
        || die "Biblioteca de archive security ausente: ${archive_lib}"

    [[ -f "${archive_inspector}" ]] \
        || die "Archive inspector ausente: ${archive_inspector}"

    # shellcheck source=/dev/null
    source "${semver_lib}"

    # shellcheck source=/dev/null
    source "${archive_lib}"
}

# =============================================================
# Source / profile selection
# =============================================================

local_source_available()
{
    [[ -f "${INSTALLER_DIR}/version" ]] \
        && [[ -f "${INSTALLER_DIR}/bin/dsm" ]] \
        && [[ -f "${INSTALLER_DIR}/bin/cap" ]] \
        && [[ -f "${INSTALLER_DIR}/core/bootstrap.sh" ]] \
        && [[ -f "${INSTALLER_DIR}/config/dsm.conf" ]]
}

select_installation_source()
{
    (( INSTALL_MODE_EXPLICIT == 0 )) || return 0

    if ! is_interactive
    then
        if local_source_available
        then
            INSTALL_MODE="local"
        else
            INSTALL_MODE="remote"
        fi

        return 0
    fi

    section "Origem da instalação"

    if local_source_available
    then
        cat <<'EOF_SOURCE'
Escolha a origem:

  1) Arquivos locais deste checkout
  2) GitHub Release oficial
EOF_SOURCE

        local answer

        read -r -p "Origem [1]: " answer

        case "${answer:-1}" in
            1|local)
                INSTALL_MODE="local"
                ;;
            2|remote|github)
                INSTALL_MODE="remote"
                ;;
            *)
                die "Origem inválida: ${answer}"
                ;;
        esac
    else
        INSTALL_MODE="remote"
        log "Checkout local incompleto; usando release remota."
    fi
}

validate_account_name()
{
    local value="$1"
    local kind="$2"

    [[ "${value}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] \
        || die "${kind} inválido: ${value}"
}

prompt_value()
{
    local variable="$1"
    local prompt="$2"
    local default="$3"
    local current="${!variable:-}"

    [[ -n "${current}" ]] && return 0

    if is_interactive
    then
        read -r -p "${prompt} [${default}]: " current
        current="${current:-${default}}"
    else
        current="${default}"
    fi

    printf -v "${variable}" '%s' "${current}"
}

select_installation_profile()
{
    section "Perfil deste node"

    if is_interactive
    then
        cat <<'EOF_ROLE'
Papéis disponíveis:

  controller
      Controlador central. Não executa servidores de jogos.

  agent
      Executa e administra instâncias de jogos.

  hybrid
      Controller e Agent na mesma máquina.
EOF_ROLE
    fi

    prompt_value \
        DSM_SERVICE_USER \
        "Usuário de serviço" \
        "${CURRENT_MACHINE_USER}"

    prompt_value \
        DSM_SERVICE_GROUP \
        "Grupo de serviço" \
        "${CURRENT_MACHINE_GROUP}"

    prompt_value \
        DSM_NODE_ROLE \
        "Papel (controller/agent/hybrid)" \
        "agent"

    validate_account_name \
        "${DSM_SERVICE_USER}" \
        "Usuário"

    validate_account_name \
        "${DSM_SERVICE_GROUP}" \
        "Grupo"

    case "${DSM_NODE_ROLE}" in
        controller|agent|hybrid)
            ;;
        *)
            die "DSM_NODE_ROLE inválido: ${DSM_NODE_ROLE}"
            ;;
    esac
}

# =============================================================
# Preflight
# =============================================================

# =============================================================
# System requirements / capabilities
# =============================================================

REQUIREMENTS_FAILED=0
REQUIREMENTS_WARNINGS=0

requirement_ok()
{
    printf '  %-30s OK\n' "$1"
}

requirement_warn()
{
    printf '  %-30s AVISO - %s\n' "$1" "$2"
    ((REQUIREMENTS_WARNINGS += 1))
}

requirement_fail()
{
    printf '  %-30s FALHA - %s\n' "$1" "$2" >&2
    ((REQUIREMENTS_FAILED += 1))
}

check_required_command()
{
    local command_name="$1"
    local description="${2:-$1}"

    if command -v "${command_name}" >/dev/null 2>&1
    then
        requirement_ok "${description}"
        return 0
    fi

    requirement_fail \
        "${description}" \
        "comando '${command_name}' não encontrado"

    return 1
}

check_optional_command()
{
    local command_name="$1"
    local description="${2:-$1}"

    if command -v "${command_name}" >/dev/null 2>&1
    then
        requirement_ok "${description}"
        return 0
    fi

    requirement_warn \
        "${description}" \
        "comando '${command_name}' não encontrado"

    return 1
}

check_linux()
{
    if [[ "$(uname -s)" == "Linux" ]]
    then
        requirement_ok "Sistema Linux"
        return 0
    fi

    requirement_fail \
        "Sistema operacional" \
        "esta versão do Agent/Controller requer Linux"

    return 1
}

check_architecture()
{
    local architecture

    architecture="$(uname -m)"

    case "${architecture}" in
        x86_64|amd64)
            requirement_ok \
                "Arquitetura ${architecture}"
            return 0
            ;;

        *)
            requirement_fail \
                "Arquitetura ${architecture}" \
                "arquitetura ainda não suportada pelo instalador Linux"

            return 1
            ;;
    esac
}

check_bash_version()
{
    local major="${BASH_VERSINFO[0]:-0}"

    if (( major >= 4 ))
    then
        requirement_ok \
            "Bash ${BASH_VERSION}"
        return 0
    fi

    requirement_fail \
        "Bash ${BASH_VERSION:-desconhecido}" \
        "Bash 4 ou superior é necessário"

    return 1
}

check_python()
{
    if ! command -v python3 >/dev/null 2>&1
    then
        requirement_fail \
            "Python 3" \
            "python3 não encontrado"

        return 1
    fi

    local python_version

    python_version="$(
        python3 -c \
            'import sys; print(".".join(map(str, sys.version_info[:3])))'
    )"

    if python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 8) else 1)
PY
    then
        requirement_ok \
            "Python ${python_version}"
        return 0
    fi

    requirement_fail \
        "Python ${python_version}" \
        "Python 3.8 ou superior é necessário"

    return 1
}

check_python_sqlite()
{
    if python3 - <<'PY' >/dev/null 2>&1
import sqlite3

connection = sqlite3.connect(":memory:")
connection.execute("SELECT 1")
connection.close()
PY
    then
        local sqlite_version

        sqlite_version="$(
            python3 - <<'PY'
import sqlite3
print(sqlite3.sqlite_version)
PY
        )"

        requirement_ok \
            "Python sqlite3 ${sqlite_version}"

        return 0
    fi

    requirement_fail \
        "Python sqlite3" \
        "módulo sqlite3 indisponível ou não funcional"

    return 1
}

normalize_database_settings()
{
    DSM_DATABASE_DRIVER="${DSM_DATABASE_DRIVER,,}"

    case "${DSM_DATABASE_DRIVER}" in
        sqlite|sqlite3)
            DSM_DATABASE_DRIVER="sqlite"
            DSM_DATABASE="${DSM_DATABASE:-${DSM_ROOT}/data/capivara.db}"
            ;;
        postgres|postgresql|pgsql)
            DSM_DATABASE_DRIVER="postgresql"
            DSM_DATABASE_PORT="${DSM_DATABASE_PORT:-5432}"
            ;;
        mysql)
            DSM_DATABASE_PORT="${DSM_DATABASE_PORT:-3306}"
            ;;
        mariadb)
            # Preserve the public alias in configuration. The runtime
            # normalizes MariaDB to the shared MySQL backend.
            DSM_DATABASE_PORT="${DSM_DATABASE_PORT:-3306}"
            ;;
        *)
            die "DSM_DATABASE_DRIVER inválido: ${DSM_DATABASE_DRIVER}"
            ;;
    esac
}

validate_database_settings()
{
    normalize_database_settings

    if [[ "${DSM_DATABASE_DRIVER}" == "sqlite" ]]
    then
        [[ -n "${DSM_DATABASE}" ]] \
            || die "DSM_DATABASE é obrigatório para SQLite."
        return 0
    fi

    [[ -n "${DSM_DATABASE_HOST}" ]] \
        || die "DSM_DATABASE_HOST é obrigatório para ${DSM_DATABASE_DRIVER}."
    [[ -n "${DSM_DATABASE_NAME}" ]] \
        || die "DSM_DATABASE_NAME é obrigatório para ${DSM_DATABASE_DRIVER}."
    [[ -n "${DSM_DATABASE_USER}" ]] \
        || die "DSM_DATABASE_USER é obrigatório para ${DSM_DATABASE_DRIVER}."
    [[ "${DSM_DATABASE_PORT}" =~ ^[0-9]+$ ]] \
        && (( DSM_DATABASE_PORT >= 1 && DSM_DATABASE_PORT <= 65535 )) \
        || die "DSM_DATABASE_PORT deve estar entre 1 e 65535."

    case "${DSM_DATABASE_TLS}" in
        disable|allow|prefer|preferred|require|required|verify-ca|verify-full)
            ;;
        *)
            die "DSM_DATABASE_TLS inválido: ${DSM_DATABASE_TLS}"
            ;;
    esac

    if [[ -n "${DSM_DATABASE_PASSWORD_FILE}" ]]
    then
        [[ -f "${DSM_DATABASE_PASSWORD_FILE}" ]] \
            || die "Arquivo de senha do banco não encontrado: ${DSM_DATABASE_PASSWORD_FILE}"
        [[ -r "${DSM_DATABASE_PASSWORD_FILE}" ]] \
            || die "Arquivo de senha do banco não é legível: ${DSM_DATABASE_PASSWORD_FILE}"

        if [[ "$(uname -s)" == "Linux" ]] \
            && find "${DSM_DATABASE_PASSWORD_FILE}" -prune -perm /077 \
            | grep -q .
        then
            die "Arquivo de senha do banco deve usar permissão 600 ou mais restritiva."
        fi
    fi
}

check_python_database_driver()
{
    case "${DSM_DATABASE_DRIVER}" in
        sqlite)
            check_python_sqlite
            ;;
        postgresql)
            if python3 -c 'import psycopg' >/dev/null 2>&1
            then
                requirement_ok "Python psycopg"
            else
                requirement_fail \
                    "Python psycopg" \
                    "instale o pacote psycopg para PostgreSQL"
                return 1
            fi
            ;;
        mysql|mariadb)
            if python3 -c 'import mysql.connector' >/dev/null 2>&1
            then
                requirement_ok "Python mysql.connector"
            else
                requirement_fail \
                    "Python mysql.connector" \
                    "instale mysql-connector-python para MySQL/MariaDB"
                return 1
            fi
            ;;
    esac
}

check_systemd_capability()
{
    case "${INSTALL_SYSTEMD}" in
        0|no|false|skip)
            SYSTEMD_ACTIVE=0
            requirement_warn "systemd" "desabilitado por DSM_INSTALL_SYSTEMD"
            return 0
            ;;
        auto|1|yes|true)
            ;;
        *)
            requirement_fail "systemd" "DSM_INSTALL_SYSTEMD inválido"
            return 1
            ;;
    esac
    if [[ -d /run/systemd/system ]] \
        && command -v systemctl >/dev/null 2>&1 \
        && systemctl show-environment >/dev/null 2>&1
    then
        SYSTEMD_ACTIVE=1

        requirement_ok \
            "systemd"

        return 0
    fi

    SYSTEMD_ACTIVE=0

    requirement_warn \
        "systemd" \
        "não está ativo; serviços não serão registrados/iniciados"

    return 0
}

check_disk_space()
{
    local target="${DSM_ROOT}"
    local probe="${target}"

    while [[ ! -e "${probe}" && "${probe}" != "/" ]]
    do
        probe="$(dirname "${probe}")"
    done

    local available_kb

    available_kb="$(
        df -Pk "${probe}" \
            | awk 'NR == 2 {print $4}'
    )"

    [[ "${available_kb}" =~ ^[0-9]+$ ]] \
        || {
            requirement_warn \
                "Espaço em disco" \
                "não foi possível determinar espaço disponível"

            return 0
        }

    local available_gb=$((
        (available_kb + 1048575) / 1048576
    ))

    if (( available_gb >= 10 ))
    then
        requirement_ok \
            "Disco livre ${available_gb} GB"
    else
        requirement_warn \
            "Disco livre ${available_gb} GB" \
            "menos de 10 GB livres; servidores de jogos podem exigir muito mais"
    fi
}

check_memory()
{
    [[ -r /proc/meminfo ]] \
        || {
            requirement_warn \
                "Memória RAM" \
                "não foi possível consultar /proc/meminfo"

            return 0
        }

    local memory_kb

    memory_kb="$(
        awk \
            '/^MemTotal:/ {print $2}' \
            /proc/meminfo
    )"

    [[ "${memory_kb}" =~ ^[0-9]+$ ]] \
        || return 0

    local memory_mb=$((
        memory_kb / 1024
    ))

    if (( memory_mb >= 2048 ))
    then
        requirement_ok \
            "RAM $((memory_mb / 1024)) GB"
    else
        requirement_warn \
            "RAM ${memory_mb} MB" \
            "menos de 2 GB; capacidade operacional será limitada"
    fi
}

check_dns()
{
    if getent ahosts github.com >/dev/null 2>&1
    then
        requirement_ok \
            "DNS"
        return 0
    fi

    requirement_fail \
        "DNS" \
        "não foi possível resolver github.com"

    return 1
}

check_github_connectivity()
{
    if curl \
        --silent \
        --show-error \
        --fail \
        --head \
        --connect-timeout 10 \
        https://api.github.com \
        >/dev/null 2>&1
    then
        requirement_ok \
            "HTTPS GitHub"

        return 0
    fi

    if [[ "${INSTALL_MODE}" == "remote" ]]
    then
        requirement_fail \
            "HTTPS GitHub" \
            "GitHub API inacessível"

        return 1
    fi

    requirement_warn \
        "HTTPS GitHub" \
        "indisponível; instalação local ainda pode funcionar"

    return 0
}

check_steam_capability()
{
    if [[ "${DSM_NODE_ROLE}" == "controller" ]]
    then
        printf '  %-30s N/A\n' "SteamCMD"
        return 0
    fi

    if command -v steamcmd >/dev/null 2>&1
    then
        requirement_ok \
            "SteamCMD"

        return 0
    fi

    case "${INSTALL_STEAMCMD}" in
        0|no|false)
            requirement_warn \
                "SteamCMD" \
                "não instalado; jogos Steam ficarão indisponíveis"

            return 0
            ;;

        *)
            requirement_warn \
                "SteamCMD" \
                "não encontrado; será instalado posteriormente"

            return 0
            ;;
    esac
}

system_requirements_preflight()
{
    section "Requisitos do sistema"

    REQUIREMENTS_FAILED=0
    REQUIREMENTS_WARNINGS=0

    printf '\nSistema:\n'

    check_linux || true
    check_architecture || true
    check_bash_version || true
    check_python || true
    check_python_database_driver || true

    printf '\nFerramentas obrigatórias:\n'

    check_required_command rsync "rsync" || true
    check_required_command curl "curl" || true
    check_required_command tar "tar" || true
    check_required_command gzip "gzip" || true
    check_required_command sha256sum "sha256sum" || true
    check_required_command getent "getent" || true
    check_required_command sed "sed" || true
    check_required_command awk "awk" || true
    check_required_command grep "grep" || true
    check_required_command find "find" || true
    check_required_command hostname "hostname" || true

    printf '\nAmbiente:\n'

    check_systemd_capability
    check_disk_space
    check_memory

    printf '\nRede:\n'

    check_dns || true
    check_github_connectivity || true

    printf '\nCapacidades do node:\n'

    check_steam_capability

    printf '\nResumo:\n'
    printf '  Falhas obrigatórias : %d\n' \
        "${REQUIREMENTS_FAILED}"
    printf '  Avisos              : %d\n' \
        "${REQUIREMENTS_WARNINGS}"

    if (( REQUIREMENTS_FAILED > 0 ))
    then
        die \
            "O sistema não atende aos requisitos obrigatórios do Capivara."
    fi

    log \
        "Pré-validação de requisitos concluída."
}

show_plan()
{
    section "Plano da instalação"

    printf 'Origem             : %s\n' "${INSTALL_MODE}"

    if [[ "${INSTALL_MODE}" == "remote" ]]
    then
        printf 'Release            : %s\n' "${CAPIVARA_RELEASE_TAG}"
    fi

    printf 'Papel              : %s\n' "${DSM_NODE_ROLE}"
    printf 'Conta              : %s:%s\n' \
        "${DSM_SERVICE_USER}" \
        "${DSM_SERVICE_GROUP}"
    printf 'Destino            : %s\n' "${DSM_ROOT}"
    printf 'Systemd            : %s\n' "${SYSTEMD_ACTIVE}"
    printf 'Dry-run            : %s\n' "${DRY_RUN}"
    printf 'Reinstalação       : %s\n' "${ALLOW_REINSTALL}"
    printf 'Banco              : %s\n' "${DSM_DATABASE_DRIVER}"

    if [[ "${DSM_DATABASE_DRIVER}" == "sqlite" ]]
    then
        printf 'Arquivo do banco   : %s\n' "${DSM_DATABASE}"
    else
        printf 'Servidor do banco  : %s:%s\n' \
            "${DSM_DATABASE_HOST}" \
            "${DSM_DATABASE_PORT}"
        printf 'Nome do banco      : %s\n' "${DSM_DATABASE_NAME}"
        printf 'Usuário do banco   : %s\n' "${DSM_DATABASE_USER}"
        printf 'TLS do banco       : %s\n' "${DSM_DATABASE_TLS}"
        printf 'Senha              : %s\n' \
            "$([[ -n "${DSM_DATABASE_PASSWORD_FILE}" ]] && printf 'arquivo protegido' || printf 'não configurada')"
    fi

    if is_interactive && (( ! DRY_RUN ))
    then
        local answer

        printf '\n'
        read -r -p "Continuar? [S/n]: " answer

        case "${answer:-s}" in
            s|S|sim|SIM|y|Y|yes|YES)
                ;;
            *)
                die "Instalação cancelada."
                ;;
        esac
    fi
}

# =============================================================
# GitHub
# =============================================================

github_api_host()
{
    python3 - "${CAPIVARA_GITHUB_API}" <<'PY'
import sys
from urllib.parse import urlparse

print(urlparse(sys.argv[1]).hostname or "")
PY
}

validate_github_api_trust()
{
    local host

    host="$(github_api_host)"

    [[ -n "${host}" ]] \
        || die "CAPIVARA_GITHUB_API inválido."

    if [[ -n "${GH_TOKEN}" && "${host}" != "api.github.com" ]]
    then
        die \
            "GH_TOKEN não será enviado para API GitHub personalizada: ${host}"
    fi
}

github_api_get()
{
    local url="$1"
    local -a args=(
        --fail
        --silent
        --show-error
        --location
        --connect-timeout 15
        -H "Accept: application/vnd.github+json"
        -H "X-GitHub-Api-Version: 2022-11-28"
    )

    if [[ -n "${GH_TOKEN}" ]]
    then
        args+=(
            -H "Authorization: Bearer ${GH_TOKEN}"
        )
    fi

    curl "${args[@]}" "${url}"
}

github_release_endpoint()
{
    if [[ "${CAPIVARA_RELEASE_TAG}" == "latest" ]]
    then
        printf '%s/repos/%s/releases/latest\n' \
            "${CAPIVARA_GITHUB_API}" \
            "${CAPIVARA_GITHUB_REPO}"
    else
        printf '%s/repos/%s/releases/tags/%s\n' \
            "${CAPIVARA_GITHUB_API}" \
            "${CAPIVARA_GITHUB_REPO}" \
            "${CAPIVARA_RELEASE_TAG}"
    fi
}

download_github_asset()
{
    local asset_api_url="$1"
    local output="$2"

    local -a args=(
        --fail
        --silent
        --show-error
        --location
        --retry 3
        --connect-timeout 15
        -H "Accept: application/octet-stream"
        -H "X-GitHub-Api-Version: 2022-11-28"
        -o "${output}"
    )

    if [[ -n "${GH_TOKEN}" ]]
    then
        args+=(
            -H "Authorization: Bearer ${GH_TOKEN}"
        )
    fi

    curl "${args[@]}" "${asset_api_url}"
}

# =============================================================
# Release security
# =============================================================

inspect_archive()
{
    local archive="$1"
    local output="$2"

    python3 \
        "${INSTALLER_DIR}/core/archive_inspector.py" \
        "${archive}" \
        >"${output}"
}

validate_release_archive()
{
    local archive="$1"
    local checksum="$2"
    local expected_version="$3"

    local inspection_file
    local archive_type
    local archive_member
    local archive_target
    local root

    local -a members=()

    [[ "${checksum}" =~ ^[[:xdigit:]]{64}$ ]] \
        || die "Checksum SHA-256 inválido."

    printf '%s  %s\n' \
        "${checksum}" \
        "${archive}" \
        | sha256sum -c - >/dev/null \
        || die "Checksum SHA-256 da release inválido."

    log "Checksum SHA-256 validado."

    tar -tzf "${archive}" >/dev/null 2>&1 \
        || die "Pacote TAR inválido."

    inspection_file="${BOOTSTRAP_TMP}/archive-inspection.tsv"

    inspect_archive \
        "${archive}" \
        "${inspection_file}" \
        || die "Falha inspecionando pacote."

    while IFS=$'\t' read -r \
        archive_type archive_member archive_target
    do
        [[ -n "${archive_member}" ]] \
            || die "Pacote contém membro sem nome."

        case "${archive_type}" in
            member)
                archive_validate_member \
                    "${archive_member}" \
                    || die "Caminho inseguro: ${archive_member}"
                ;;

            symlink)
                archive_validate_symlink \
                    "${archive_member}" \
                    "${archive_target}" \
                    || die \
                        "Symlink inseguro: ${archive_member} -> ${archive_target}"
                ;;

            hardlink)
                archive_validate_hardlink \
                    "${archive_member}" \
                    "${archive_target}" \
                    || die \
                        "Hardlink inseguro: ${archive_member} -> ${archive_target}"
                ;;

            *)
                die \
                    "Tipo de membro desconhecido: ${archive_type}"
                ;;
        esac

        members+=("${archive_member}")

    done <"${inspection_file}"

    (( ${#members[@]} > 0 )) \
        || die "Pacote vazio."

    root="$(
        archive_release_members_root \
            "${members[@]}"
    )" || die "Root da release inválido."

    local root_version

    root_version="$(
        archive_release_root_version \
            "${root}"
    )" || die "Versão do root inválida."

    [[ "${root_version}" == "${expected_version}" ]] \
        || die \
            "Root da release não corresponde à versão esperada: ${root_version} != ${expected_version}"

    RELEASE_ROOT="${root}"

    log "Estrutura do archive validada: ${RELEASE_ROOT}"
}

verify_package_manifest()
{
    local package_root="$1"
    local external_manifest="$2"
    local expected_version="$3"
    local expected_archive="$4"

    local internal_manifest="${package_root}/release-manifest.json"

    [[ -f "${internal_manifest}" ]] \
        || die "release-manifest.json ausente."

    cmp -s \
        "${external_manifest}" \
        "${internal_manifest}" \
        || die \
            "Manifest externo difere do manifest interno do pacote."

    python3 - \
        "${internal_manifest}" \
        "${package_root}" \
        "${expected_version}" \
        "${expected_archive}" <<'PY'
import json
import pathlib
import sys

manifest_path, root_path, expected_version, expected_archive = sys.argv[1:]

root = pathlib.Path(root_path)

with open(manifest_path, encoding="utf-8") as f:
    manifest = json.load(f)

if manifest.get("schema_version") != 1:
    raise SystemExit("manifest schema_version inválido")

if manifest.get("kind") != "CapivaraReleaseManifest":
    raise SystemExit("manifest kind inválido")

if manifest.get("name") != "capivara-dsm":
    raise SystemExit("manifest name inválido")

if manifest.get("version") != expected_version:
    raise SystemExit("manifest version não corresponde à release")

if manifest.get("archive") != expected_archive:
    raise SystemExit("manifest archive não corresponde à release")

required = manifest.get("required_files")

if not isinstance(required, list) or not required:
    raise SystemExit("manifest required_files inválido")

for relative in required:
    if (
        not isinstance(relative, str)
        or relative.startswith("/")
        or ".." in pathlib.PurePosixPath(relative).parts
    ):
        raise SystemExit(
            f"required_files contém caminho inseguro: {relative!r}"
        )

    if not (root / relative).is_file():
        raise SystemExit(
            f"arquivo obrigatório ausente: {relative}"
        )
PY
}

verify_package_version()
{
    local package_root="$1"
    local expected_version="$2"
    local package_version

    [[ -s "${package_root}/version" ]] \
        || die "Arquivo version ausente."

    package_version="$(
        tr -d '\r\n' <"${package_root}/version"
    )"

    is_semver "${package_version}" \
        || die "Versão interna inválida: ${package_version}"

    [[ "${package_version}" == "${expected_version}" ]] \
        || die \
            "version (${package_version}) difere da release (${expected_version})."
}

# =============================================================
# Remote acquisition
# =============================================================

acquire_remote_source()
{
    section "Origem remota"

    validate_github_api_trust

    BOOTSTRAP_TMP="$(
        mktemp -d -t capivara-installer.XXXXXX
    )"

    local metadata="${BOOTSTRAP_TMP}/release.json"
    local endpoint

    endpoint="$(github_release_endpoint)"

    if ! github_api_get "${endpoint}" >"${metadata}"
    then
        die \
            "Não foi possível consultar a GitHub Release antes da instalação."
    fi

    local release_info

    release_info="$(
        python3 - "${metadata}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    release = json.load(f)
tag = release.get("tag_name") or ""

version = tag[1:] if tag.startswith("v") else tag

archive_name = f"capivara-dsm-{version}.tar.gz"
checksum_name = archive_name + ".sha256"
manifest_name = f"capivara-dsm-{version}.manifest.json"

assets = {
    asset.get("name"): asset.get("url")
    for asset in release.get("assets", [])
    if asset.get("name") and asset.get("url")
}

print(tag)
print(version)
print(archive_name)
print(assets.get(archive_name, ""))
print(checksum_name)
print(assets.get(checksum_name, ""))
print(manifest_name)
print(assets.get(manifest_name, ""))
PY
    )"

    local tag
    local version
    local archive_name
    local archive_url
    local checksum_name
    local checksum_url
    local manifest_name
    local manifest_url

    tag="$(sed -n '1p' <<<"${release_info}")"
    version="$(sed -n '2p' <<<"${release_info}")"
    archive_name="$(sed -n '3p' <<<"${release_info}")"
    archive_url="$(sed -n '4p' <<<"${release_info}")"
    checksum_name="$(sed -n '5p' <<<"${release_info}")"
    checksum_url="$(sed -n '6p' <<<"${release_info}")"
    manifest_name="$(sed -n '7p' <<<"${release_info}")"
    manifest_url="$(sed -n '8p' <<<"${release_info}")"

    [[ -n "${tag}" ]] \
        || die "Release sem tag_name."

    is_semver "${version}" \
        || die "Tag da release não representa SemVer válida: ${tag}"

    [[ -n "${archive_url}" ]] \
        || die "Asset oficial ausente: ${archive_name}"

    [[ -n "${checksum_url}" ]] \
        || die "Checksum oficial ausente: ${checksum_name}"

    [[ -n "${manifest_url}" ]] \
        || die "Manifest oficial ausente: ${manifest_name}"

    RELEASE_VERSION="${version}"
    RELEASE_ARCHIVE="${BOOTSTRAP_TMP}/${archive_name}"
    RELEASE_MANIFEST="${BOOTSTRAP_TMP}/${manifest_name}"

    local checksum_file="${BOOTSTRAP_TMP}/${checksum_name}"

    log "Baixando ${archive_name}"

    download_github_asset \
        "${archive_url}" \
        "${RELEASE_ARCHIVE}"

    download_github_asset \
        "${checksum_url}" \
        "${checksum_file}"

    download_github_asset \
        "${manifest_url}" \
        "${RELEASE_MANIFEST}"

    [[ -s "${RELEASE_ARCHIVE}" ]] \
        || die "Archive remoto vazio."

    [[ -s "${checksum_file}" ]] \
        || die "Checksum remoto vazio."

    [[ -s "${RELEASE_MANIFEST}" ]] \
        || die "Manifest remoto vazio."

    local checksum

    checksum="$(
        awk 'NR == 1 {print $1}' \
            "${checksum_file}"
    )"

    validate_release_archive \
        "${RELEASE_ARCHIVE}" \
        "${checksum}" \
        "${RELEASE_VERSION}"

    local extract_dir="${BOOTSTRAP_TMP}/source"

    mkdir -p "${extract_dir}"

    # Só ocorre depois de SHA256 + inspeção completa do archive.
    tar -xzf \
        "${RELEASE_ARCHIVE}" \
        -C "${extract_dir}"

    DSM_SOURCE="${extract_dir}/${RELEASE_ROOT}"

    [[ -d "${DSM_SOURCE}" ]] \
        || die "Root extraído não encontrado."

    verify_package_version \
        "${DSM_SOURCE}" \
        "${RELEASE_VERSION}"

    verify_package_manifest \
        "${DSM_SOURCE}" \
        "${RELEASE_MANIFEST}" \
        "${RELEASE_VERSION}" \
        "${archive_name}"

    log \
        "Release ${RELEASE_VERSION} integralmente validada antes da instalação."
}

# =============================================================
# Local acquisition
# =============================================================

acquire_source()
{
    if [[ "${INSTALL_MODE}" == "local" ]]
    then
        local_source_available \
            || die "Checkout local incompleto."

        DSM_SOURCE="${INSTALLER_DIR}"

        log "Usando checkout local."
        return 0
    fi

    acquire_remote_source
}

# =============================================================
# Source validation
# =============================================================

verify_source_tree()
{
    local -a required=(
        version
        bin/dsm
        bin/cap
        core/bootstrap.sh
        core/semver.sh
        core/archive_security.sh
        core/archive_inspector.py
        config/dsm.conf
        database/manager.py
        database/registry.py
        database/registry_repository.py
        database/runtime_backend.py
        database/backend_factory.py
        database/migrations/001_initial.sql
        database/migrations_postgresql/001_initial.sql
        database/migrations_mysql/001_initial.sql
        systemd/dsm-dashboard.service
    )

    local -a missing=()
    local relative

    for relative in "${required[@]}"
    do
        [[ -e "${DSM_SOURCE}/${relative}" ]] \
            || missing+=("${relative}")
    done

    if (( ${#missing[@]} > 0 ))
    then
        printf '[Capivara][ERRO] Pacote incompleto:\n' >&2
        printf '  - %s\n' "${missing[@]}" >&2
        exit 1
    fi
}

# =============================================================
# Existing installation guard
# =============================================================

read_package_version()
{
    local file="$1"
    local value=""

    if [[ -f "${file}" ]]
    then
        IFS= read -r value <"${file}" || true
    fi

    printf '%s' "${value:-desconhecida}"
}

guard_existing_installation()
{
    if [[ ! -f "${DSM_ROOT}/version" \
        && ! -f "${DSM_ROOT}/config/dsm.conf" \
        && ! -x "${DSM_ROOT}/bin/dsm" ]]
    then
        return 0
    fi

    local installed_version
    local package_version

    installed_version="$(
        read_package_version \
            "${DSM_ROOT}/version"
    )"

    package_version="$(
        read_package_version \
            "${DSM_SOURCE}/version"
    )"

    if (( ALLOW_REINSTALL ))
    then
        warn \
            "Reinstalação explícita: ${installed_version} -> ${package_version}"

        warn \
            "Configurações, banco, instâncias e estado persistente serão preservados."

        return 0
    fi

    cat >&2 <<EOF_EXISTING

==============================================================
 INSTALAÇÃO EXISTENTE DETECTADA
==============================================================

Diretório        : ${DSM_ROOT}
Versão instalada : ${installed_version}
Versão do pacote : ${package_version}

O install.sh não sobrescreve automaticamente uma instalação existente.

Para atualizar uma instalação existente, utilize:

    dsm update check
    dsm update run

--reinstall deve ser usado somente para uma reinstalação intencional.
EOF_EXISTING

    exit 1
}

# =============================================================
# Service account
# =============================================================

ensure_service_account()
{
    section "Conta de serviço"

    if (( DRY_RUN ))
    then
        log \
            "[DRY-RUN] garantiria ${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}"

        DSM_SERVICE_HOME="${DSM_SERVICE_HOME:-${DSM_ROOT}}"
        return 0
    fi

    if ! getent group \
        "${DSM_SERVICE_GROUP}" >/dev/null 2>&1
    then
        groupadd \
            --system \
            "${DSM_SERVICE_GROUP}"
    fi

    if ! id \
        "${DSM_SERVICE_USER}" >/dev/null 2>&1
    then
        useradd \
            --system \
            --gid "${DSM_SERVICE_GROUP}" \
            --home-dir "${DSM_ROOT}" \
            --shell /usr/sbin/nologin \
            "${DSM_SERVICE_USER}"
    else
        local primary_group

        primary_group="$(
            id -gn "${DSM_SERVICE_USER}"
        )"

        if [[ "${primary_group}" != "${DSM_SERVICE_GROUP}" ]]
        then
            usermod \
                -a \
                -G "${DSM_SERVICE_GROUP}" \
                "${DSM_SERVICE_USER}"
        fi
    fi

    DSM_SERVICE_HOME="$(
        getent passwd "${DSM_SERVICE_USER}" \
            | cut -d: -f6
    )"

    [[ -n "${DSM_SERVICE_HOME}" ]] \
        || die \
            "Não foi possível determinar o home de ${DSM_SERVICE_USER}."
}

# =============================================================
# Project files
# =============================================================

install_project_files()
{
    section "Arquivos"

    if (( DRY_RUN ))
    then
        log \
            "[DRY-RUN] copiaria ${DSM_SOURCE}/ -> ${DSM_ROOT}/ preservando configurações e estado persistente."

        return 0
    fi

    mkdir -p "${DSM_ROOT}/config"

    rsync -a \
        --exclude "config/dsm.conf" \
        --exclude "config/agent.conf" \
        --exclude "data/" \
        --exclude "instances/" \
        --exclude "logs/" \
        --exclude "cache/" \
        --exclude "tmp/" \
        --exclude "runtime/state/" \
        "${DSM_SOURCE}/" \
        "${DSM_ROOT}/"

    if [[ ! -f "${DSM_ROOT}/config/dsm.conf" ]]
    then
        cp \
            "${DSM_SOURCE}/config/dsm.conf" \
            "${DSM_ROOT}/config/dsm.conf"
    fi

    mkdir -p \
        "${DSM_ROOT}/cache" \
        "${DSM_ROOT}/logs" \
        "${DSM_ROOT}/tmp" \
        "${DSM_ROOT}/data" \
        "${DSM_ROOT}/runtime" \
        "${DSM_ROOT}/instances"

    find \
        "${DSM_ROOT}" \
        -type f \
        -name '*.sh' \
        -exec chmod +x {} \;

    chmod +x "${DSM_BIN}"
    chmod +x "${CAP_BIN}"

    chown -R \
        "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "${DSM_ROOT}/cache" \
        "${DSM_ROOT}/logs" \
        "${DSM_ROOT}/tmp" \
        "${DSM_ROOT}/data" \
        "${DSM_ROOT}/runtime" \
        "${DSM_ROOT}/instances"
}

# =============================================================
# Configuration
# =============================================================

set_shell_config_value()
{
    local file="$1"
    local key="$2"
    local value="$3"
    local escaped

    [[ "${value}" != *$'\n'* \
        && "${value}" != *'"'* ]] \
        || die "Valor inválido para ${key}."

    escaped="${value//\\/\\\\}"
    escaped="${escaped//&/\\&}"
    escaped="${escaped//|/\\|}"

    if grep -q "^${key}=" "${file}"
    then
        sed -i \
            "s|^${key}=.*|${key}=\"${escaped}\"|" \
            "${file}"
    else
        printf '%s="%s"\n' \
            "${key}" \
            "${value}" \
            >>"${file}"
    fi
}

write_dsm_config()
{
    (( DRY_RUN )) \
        && {
            log "[DRY-RUN] atualizaria dsm.conf."
            return 0
        }

    local config="${DSM_ROOT}/config/dsm.conf"
    local version

    [[ -f "${config}" ]] \
        || die "dsm.conf ausente."

    version="$(
        tr -d '\r\n' <"${DSM_ROOT}/version"
    )"

    set_shell_config_value \
        "${config}" \
        DSM_VERSION \
        "${version}"

    set_shell_config_value \
        "${config}" \
        INSTALLER_VERSION \
        "${version}"

    set_shell_config_value \
        "${config}" \
        DSM_DATA_DIR \
        "${DSM_ROOT}/data"

    set_shell_config_value \
        "${config}" \
        DSM_DATABASE_DRIVER \
        "${DSM_DATABASE_DRIVER}"

    set_shell_config_value \
        "${config}" \
        DSM_DATABASE \
        "${DSM_DATABASE}"

    set_shell_config_value "${config}" DSM_DATABASE_HOST "${DSM_DATABASE_HOST}"
    set_shell_config_value "${config}" DSM_DATABASE_PORT "${DSM_DATABASE_PORT}"
    set_shell_config_value "${config}" DSM_DATABASE_NAME "${DSM_DATABASE_NAME}"
    set_shell_config_value "${config}" DSM_DATABASE_USER "${DSM_DATABASE_USER}"
    set_shell_config_value \
        "${config}" \
        DSM_DATABASE_PASSWORD_FILE \
        "${DSM_DATABASE_PASSWORD_FILE}"
    set_shell_config_value "${config}" DSM_DATABASE_TLS "${DSM_DATABASE_TLS}"

    set_shell_config_value \
        "${config}" \
        DSM_USER \
        "${DSM_SERVICE_USER}"

    set_shell_config_value \
        "${config}" \
        DSM_GROUP \
        "${DSM_SERVICE_GROUP}"

    set_shell_config_value \
        "${config}" \
        DSM_HOME \
        "${DSM_SERVICE_HOME}"

    chown \
        "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "${config}"

    chmod 640 "${config}"
}

write_agent_config()
{
    (( DRY_RUN )) \
        && {
            log "[DRY-RUN] atualizaria agent.conf."
            return 0
        }

    local config="${DSM_ROOT}/config/agent.conf"

    if [[ ! -f "${config}" ]]
    then
        cat >"${config}" <<EOF_AGENT
#############################################
# Capivara DSM Node
#############################################

AGENT_ID=""
AGENT_NAME=""
AGENT_STATUS="pending"

DSM_NODE_ID="$(hostname)"
DSM_NODE_ROLE="${DSM_NODE_ROLE}"

INSTANCE_ROOT="${DSM_ROOT}/instances"

DSM_USER="${DSM_SERVICE_USER}"
DSM_GROUP="${DSM_SERVICE_GROUP}"

STEAMCMD_ROOT="${STEAMCMD_ROOT}"
EOF_AGENT
    else
        set_shell_config_value \
            "${config}" \
            DSM_NODE_ROLE \
            "${DSM_NODE_ROLE}"

        set_shell_config_value \
            "${config}" \
            DSM_USER \
            "${DSM_SERVICE_USER}"

        set_shell_config_value \
            "${config}" \
            DSM_GROUP \
            "${DSM_SERVICE_GROUP}"

        set_shell_config_value \
            "${config}" \
            STEAMCMD_ROOT \
            "${STEAMCMD_ROOT}"
    fi

    chown \
        "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "${config}"

    chmod 640 "${config}"
}

initialize_runtime_state()
{
    local initializer="${DSM_ROOT}/dashboard/state/init_state.sh"
    [[ -f "${initializer}" ]] || die "Inicializador de estado ausente: ${initializer}"
    if (( DRY_RUN ))
    then
        log "[DRY-RUN] inicializaria o estado operacional do Dashboard."
        return 0
    fi
    DSM_ROOT="${DSM_ROOT}" bash "${initializer}"
    chown -R "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "${DSM_ROOT}/dashboard/state"
}

# =============================================================
# Database
# =============================================================

initialize_database()
{
    section "Banco de dados"

    if (( DRY_RUN ))
    then
        log \
            "[DRY-RUN] inicializaria/aplicaria migrações no backend ${DSM_DATABASE_DRIVER}"

        return 0
    fi

    run_database_manager init

    chown -R \
        "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "${DSM_ROOT}/data"

    chmod 750 \
        "${DSM_ROOT}/data"

    [[ "${DSM_DATABASE_DRIVER}" != "sqlite" \
        || ! -f "${DSM_DATABASE}" ]] \
        || chmod 640 \
            "${DSM_DATABASE}"
}

run_database_manager()
{
    local command="$1"
    local -a arguments=(
        "${DSM_ROOT}/database/manager.py"
        --root "${DSM_ROOT}"
        --driver "${DSM_DATABASE_DRIVER}"
    )

    if [[ "${DSM_DATABASE_DRIVER}" == "sqlite" ]]
    then
        arguments+=(--database "${DSM_DATABASE}")
    else
        arguments+=(
            --database-name "${DSM_DATABASE_NAME}"
            --host "${DSM_DATABASE_HOST}"
            --port "${DSM_DATABASE_PORT}"
            --user "${DSM_DATABASE_USER}"
            --tls "${DSM_DATABASE_TLS}"
        )

        [[ -z "${DSM_DATABASE_PASSWORD_FILE}" ]] \
            || arguments+=(--password-file "${DSM_DATABASE_PASSWORD_FILE}")
    fi

    python3 "${arguments[@]}" "${command}"
}

initialize_infrastructure_identity()
{
    section "Identidade de infraestrutura"

    if (( DRY_RUN ))
    then
        log \
            "[DRY-RUN] criaria/reconciliaria a identidade ${DSM_NODE_ROLE} pelo Registry."
        return 0
    fi

    local registry="${DSM_ROOT}/database/registry.py"
    local config="${DSM_ROOT}/config/agent.conf"
    local host
    local output
    local parsed
    local node_id
    local controller_id
    local agent_id
    local agent_status
    local placement_ready

    [[ -f "${registry}" ]] \
        || die "Registry ausente: ${registry}"

    host="$(hostname)"

    output="$(
        env \
            DSM_ROOT="${DSM_ROOT}" \
            DSM_DATABASE_DRIVER="${DSM_DATABASE_DRIVER}" \
            DSM_DATABASE="${DSM_DATABASE}" \
            DSM_DATABASE_HOST="${DSM_DATABASE_HOST}" \
            DSM_DATABASE_PORT="${DSM_DATABASE_PORT}" \
            DSM_DATABASE_NAME="${DSM_DATABASE_NAME}" \
            DSM_DATABASE_USER="${DSM_DATABASE_USER}" \
            DSM_DATABASE_PASSWORD_FILE="${DSM_DATABASE_PASSWORD_FILE}" \
            DSM_DATABASE_TLS="${DSM_DATABASE_TLS}" \
            python3 "${registry}" \
                --root "${DSM_ROOT}" \
                bootstrap-profile \
                --profile "${DSM_NODE_ROLE}" \
                --hostname "${host}"
    )" || die "Falha ao inicializar identidade de infraestrutura."

    parsed="$(
        python3 -c '
import json
import sys
payload = json.load(sys.stdin)
keys = ("node_id", "controller_id", "agent_id", "agent_status", "placement_ready")
print("\t".join("" if payload.get(key) is None else str(payload.get(key)) for key in keys))
' <<<"${output}"
    )" || die "Resposta inválida do bootstrap de infraestrutura."

    IFS=$'\t' read -r \
        node_id controller_id agent_id agent_status placement_ready \
        <<<"${parsed}"

    [[ -n "${node_id}" ]] \
        || die "Bootstrap não retornou DSM_NODE_ID."

    set_shell_config_value \
        "${config}" \
        DSM_NODE_ID \
        "${node_id}"

    if [[ "${DSM_NODE_ROLE}" == "agent" \
        || "${DSM_NODE_ROLE}" == "hybrid" ]]
    then
        [[ -n "${agent_id}" && -n "${agent_status}" ]] \
            || die "Bootstrap não retornou identidade válida de Agent."

        set_shell_config_value \
            "${config}" \
            AGENT_ID \
            "${agent_id}"

        set_shell_config_value \
            "${config}" \
            AGENT_NAME \
            "Agent ${host}"

        set_shell_config_value \
            "${config}" \
            AGENT_STATUS \
            "${agent_status}"
    fi

    chown \
        "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "${config}"
    chmod 640 "${config}"

    log \
        "Identidade ${DSM_NODE_ROLE} pronta: node=${node_id} controller=${controller_id:-nenhum} agent=${agent_id:-nenhum} placement_ready=${placement_ready}."
}

# =============================================================
# CLI
# =============================================================

install_cli()
{
    run mkdir -p "$(dirname "${DSM_LINK}")"
    run mkdir -p "$(dirname "${CAP_LINK}")"

    run ln -sf \
        "${DSM_BIN}" \
        "${DSM_LINK}"

    run ln -sf \
        "${CAP_BIN}" \
        "${CAP_LINK}"

    if (( ! DRY_RUN ))
    then
        chmod +x "${DSM_LINK}"
        chmod +x "${CAP_LINK}"
    fi
}

# =============================================================
# systemd
# =============================================================

install_systemd_units()
{
    if (( SYSTEMD_ACTIVE == 0 ))
    then
        warn \
            "Etapa systemd ignorada de forma segura."

        return 0
    fi

    if (( DRY_RUN ))
    then
        log \
            "[DRY-RUN] instalaria unidades systemd e desabilitaria workers legados."

        return 0
    fi

    [[ -d "${DSM_ROOT}/systemd" ]] \
        || return 0

    mkdir -p "${SYSTEMD_DIR}"

    local source_unit
    local name
    local destination
    local unit

    while IFS= read -r -d '' source_unit
    do
        name="$(basename "${source_unit}")"
        destination="${SYSTEMD_DIR}/${name}"

        cp -f \
            "${source_unit}" \
            "${destination}"

        sed -i \
            -e "s|{{DSM_USER}}|${DSM_SERVICE_USER}|g" \
            -e "s|{{DSM_GROUP}}|${DSM_SERVICE_GROUP}|g" \
            -e "s|/opt/dsm|${DSM_ROOT}|g" \
            "${destination}"

    done < <(
        find \
            "${DSM_ROOT}/systemd" \
            -maxdepth 1 \
            -type f \
            \( -name '*.service' -o -name '*.timer' \) \
            -print0
    )

    systemctl daemon-reload

    local -a core_units=(
        dsm-monitor.service
        dsm-scheduler.service
        dsm-alert-engine.service
        dsm-dashboard.service
        dsm-dashboard-worker.service
        dsm-notification-engine.timer
        dsm-notification-center.timer
    )

    for unit in "${core_units[@]}"
    do
        [[ -f "${SYSTEMD_DIR}/${unit}" ]] \
            && systemctl enable "${unit}"
    done

    local -a legacy_worker_units=(
        dsm-backup-worker.service
        dsm-events-worker.service
        dsm-metrics-worker.service
        dsm-mods-worker.service
        dsm-server-worker.service
    )

    for unit in "${legacy_worker_units[@]}"
    do
        if [[ -f "${SYSTEMD_DIR}/${unit}" ]]
        then
            systemctl \
                disable \
                --now \
                "${unit}" \
                2>/dev/null \
                || true
        fi
    done
}

# =============================================================
# SteamCMD
# =============================================================

should_install_steamcmd()
{
    case "${INSTALL_STEAMCMD}" in
        1|yes|true)
            return 0
            ;;

        0|no|false)
            return 1
            ;;

        auto)
            [[ "${DSM_NODE_ROLE}" == "agent" \
                || "${DSM_NODE_ROLE}" == "hybrid" ]] \
                || return 1

            if is_interactive
            then
                local answer

                printf '\n'
                read -r -p \
                    "Instalar/verificar SteamCMD? [S/n]: " \
                    answer

                case "${answer:-s}" in
                    s|S|sim|SIM|y|Y|yes|YES)
                        return 0
                        ;;
                    *)
                        return 1
                        ;;
                esac
            fi

            return 0
            ;;

        *)
            die \
                "DSM_INSTALL_STEAMCMD inválido: ${INSTALL_STEAMCMD}"
            ;;
    esac
}

install_steamcmd()
{
    [[ "${DSM_NODE_ROLE}" != "controller" ]] \
        || return 0

    should_install_steamcmd \
        || return 0

    command -v steamcmd >/dev/null 2>&1 \
        && return 0

    if (( DRY_RUN ))
    then
        log \
            "[DRY-RUN] instalaria SteamCMD em ${STEAMCMD_ROOT}"

        return 0
    fi

    local steam_tmp

    steam_tmp="$(
        mktemp -d -t capivara-steamcmd.XXXXXX
    )"

    local archive="${steam_tmp}/steamcmd_linux.tar.gz"

    curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --retry 3 \
        -o "${archive}" \
        "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"

    tar -tzf "${archive}" >/dev/null \
        || {
            rm -rf -- "${steam_tmp}"
            die "Pacote SteamCMD inválido."
        }

    mkdir -p "${STEAMCMD_ROOT}"

    tar -xzf \
        "${archive}" \
        -C "${STEAMCMD_ROOT}"

    rm -rf -- "${steam_tmp}"

    [[ -x "${STEAMCMD_ROOT}/steamcmd.sh" ]] \
        || die "steamcmd.sh não encontrado."

    chown -R \
        "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" \
        "${STEAMCMD_ROOT}"

    ln -sf \
        "${STEAMCMD_ROOT}/steamcmd.sh" \
        /usr/local/bin/steamcmd
}

# =============================================================
# Validation
# =============================================================

validate_installation()
{
    if (( DRY_RUN ))
    then
        log \
            "Dry-run concluído sem alterações persistentes."

        return 0
    fi

    [[ -x "${DSM_BIN}" ]] \
        || die "CLI ausente: ${DSM_BIN}"

    [[ -x "${CAP_BIN}" ]] \
        || die "CLI ausente: ${CAP_BIN}"

    [[ -e "${DSM_LINK}" ]] \
        || die "Comando global ausente: ${DSM_LINK}"

    [[ -e "${CAP_LINK}" ]] \
        || die "Comando global ausente: ${CAP_LINK}"

    run_database_manager check >/dev/null \
        || die "Banco inválido após instalação."

    if (( SYSTEMD_ACTIVE ))
    then
        local unit

        for unit in \
            dsm-monitor.service \
            dsm-scheduler.service \
            dsm-dashboard.service
        do
            [[ -f "${SYSTEMD_DIR}/${unit}" ]] \
                || die "Unidade ausente: ${unit}"
        done
    fi
}

# =============================================================
# Main
# =============================================================

main()
{
    parse_args "$@"

    require_root
    bootstrap_security

    select_installation_source
    select_installation_profile
    validate_database_settings

    # Ainda não altera o sistema.
    system_requirements_preflight
    show_plan

    acquire_source
    verify_source_tree

    guard_existing_installation

    # Alterações persistentes começam daqui.
    ensure_service_account
    install_project_files

    write_dsm_config
    write_agent_config
    initialize_runtime_state

    initialize_database
    initialize_infrastructure_identity

    install_cli
    install_systemd_units
    install_steamcmd

    validate_installation

    section "Capivara DSM instalado com sucesso"

    printf 'Origem            : %s\n' "${INSTALL_MODE}"
    printf 'Node              : %s\n' "${DSM_NODE_ROLE}"
    printf 'Conta             : %s:%s\n' \
        "${DSM_SERVICE_USER}" \
        "${DSM_SERVICE_GROUP}"
    printf 'Systemd           : %s\n' "${SYSTEMD_ACTIVE}"
    printf 'Comando           : %s\n' "${DSM_LINK}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    main "$@"
fi
