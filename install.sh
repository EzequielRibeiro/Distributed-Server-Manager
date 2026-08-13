#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Bootstrap / Installation Manager
# =============================================================

set -Eeuo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_SOURCE="${INSTALLER_DIR}"
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_BIN="${DSM_ROOT}/bin/dsm"
DSM_LINK="/usr/local/bin/dsm"
SYSTEMD_DIR="/etc/systemd/system"
CURRENT_MACHINE_USER="${SUDO_USER:-$(id -un)}"
CURRENT_MACHINE_GROUP="$(id -gn "${CURRENT_MACHINE_USER}")"
DEFAULT_SERVICE_USER="${CURRENT_MACHINE_USER}"
DEFAULT_SERVICE_GROUP="${CURRENT_MACHINE_GROUP}"
DEFAULT_NODE_ROLE="agent"
STEAMCMD_ROOT="${STEAMCMD_ROOT:-/opt/steamcmd}"

CAPIVARA_GITHUB_REPO="${CAPIVARA_GITHUB_REPO:-EzequielRibeiro/capivara-dsm}"
CAPIVARA_GITHUB_API="${CAPIVARA_GITHUB_API:-https://api.github.com}"
CAPIVARA_RELEASE_TAG="${CAPIVARA_RELEASE_TAG:-latest}"
GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

DSM_SERVICE_USER="${DSM_SERVICE_USER:-}"
DSM_SERVICE_GROUP="${DSM_SERVICE_GROUP:-}"
DSM_SERVICE_HOME="${DSM_SERVICE_HOME:-}"
DSM_NODE_ROLE="${DSM_NODE_ROLE:-}"
NON_INTERACTIVE="${DSM_NON_INTERACTIVE:-0}"
INSTALL_STEAMCMD="${DSM_INSTALL_STEAMCMD:-auto}"
INSTALL_MODE="${DSM_INSTALL_SOURCE:-remote}"
INSTALL_MODE_EXPLICIT=0
if [[ -n "${DSM_INSTALL_SOURCE:-}" ]]
then
    INSTALL_MODE_EXPLICIT=1
fi
ALLOW_REINSTALL=0
BOOTSTRAP_TMP=""

log()  { printf '[Capivara] %s\n' "$*"; }
warn() { printf '[Capivara][AVISO] %s\n' "$*" >&2; }
die()  { printf '[Capivara][ERRO] %s\n' "$*" >&2; exit 1; }

section() {
    printf '\n==============================================================\n'
    printf ' %s\n' "$1"
    printf '==============================================================\n'
}

explain() {
    printf '\n[O que vai acontecer]\n%s\n' "$1"
}

show_banner() {
    cat <<'EOF_BANNER'

  ╔══════════════════════════════════════════════════════════════╗
  ║                                                              ║
  ║       ██████╗ █████╗ ██████╗ ██╗██╗   ██╗ █████╗ ██████╗    ║
  ║      ██╔════╝██╔══██╗██╔══██╗██║██║   ██║██╔══██╗██╔══██╗   ║
  ║      ██║     ███████║██████╔╝██║██║   ██║███████║██████╔╝   ║
  ║      ██║     ██╔══██║██╔═══╝ ██║╚██╗ ██╔╝██╔══██║██╔══██╗   ║
  ║      ╚██████╗██║  ██║██║     ██║ ╚████╔╝ ██║  ██║██║  ██║   ║
  ║       ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═╝   ║
  ║                                                              ║
  ║                 DISTRIBUTED SERVER MANAGER                   ║
  ║                     INSTALLATION MANAGER                     ║
  ║                                                              ║
  ╚══════════════════════════════════════════════════════════════╝
EOF_BANNER
}

show_welcome() {
    cat <<'EOF_WELCOME'

Este assistente instala e prepara o Capivara DSM neste servidor.
Durante o processo ele explicará cada etapa antes de executá-la.

O instalador poderá:
  - baixar a última release estável do GitHub ou usar arquivos locais;
  - verificar e instalar dependências básicas;
  - criar/configurar a conta de serviço do Capivara;
  - preparar diretórios, configuração e unidades systemd;
  - instalar SteamCMD somente quando este node executar jogos.

Nenhuma instância de jogo é criada automaticamente nesta etapa.
EOF_WELCOME
}

show_credits() {
    cat <<'EOF_CREDITS'

Projeto idealizado e desenvolvido por:
  Ezequiel Aléssio Ribeiro

Ferramenta de apoio ao desenvolvimento:
  ChatGPT — OpenAI
EOF_CREDITS
}

usage() {
    cat <<EOF_USAGE
Uso:
  sudo ./install.sh                 Baixa e instala a última release estável
  sudo ./install.sh --local         Usa os arquivos ao lado do instalador
  sudo ./install.sh --reinstall     Reinstala explicitamente sem backup/rollback
  sudo ./install.sh --version TAG   Instala uma release específica
  sudo ./install.sh --help

Variáveis úteis:
  GH_TOKEN=...                       Acesso a releases privadas
  CAPIVARA_GITHUB_REPO=owner/repo   Repositório de distribuição
  DSM_SERVICE_USER=usuario          Sobrescreve o usuário atual da máquina
  DSM_SERVICE_GROUP=grupo           Sobrescreve o grupo primário atual
  DSM_NODE_ROLE=agent               controller, agent ou hybrid
  DSM_INSTALL_SOURCE=local          local ou remote
  DSM_NON_INTERACTIVE=1             Instalação sem perguntas
  DSM_INSTALL_STEAMCMD=auto         auto, 1 ou 0
EOF_USAGE
}

parse_args() {
    while (($#)); do
        case "$1" in
            --local) INSTALL_MODE="local"; INSTALL_MODE_EXPLICIT=1; shift ;;
            --remote) INSTALL_MODE="remote"; INSTALL_MODE_EXPLICIT=1; shift ;;
            --reinstall) ALLOW_REINSTALL=1; shift ;;
            --version)
                [[ $# -ge 2 ]] || die "--version requer uma tag."
                INSTALL_MODE="remote"; INSTALL_MODE_EXPLICIT=1; CAPIVARA_RELEASE_TAG="$2"; shift 2 ;;
            --help|-h) usage; exit 0 ;;
            *) die "Opção desconhecida: $1. Use --help." ;;
        esac
    done
    case "${INSTALL_MODE}" in local|remote) ;; *) die "Origem inválida: '${INSTALL_MODE}'. Use local ou remote." ;; esac
}

require_root() { [[ "${EUID}" -eq 0 ]] || die "Execute como root: sudo ./install.sh"; }
is_interactive() { [[ "${NON_INTERACTIVE}" != "1" && -t 0 && -t 1 ]]; }

prompt_value() {
    local var_name="$1" prompt="$2" default="$3" current="${!1:-}"
    [[ -n "${current}" ]] && return 0
    if is_interactive; then
        read -r -p "${prompt} [${default}]: " current
        current="${current:-${default}}"
    else
        current="${default}"
    fi
    printf -v "${var_name}" '%s' "${current}"
}

validate_account_name() {
    local value="$1" kind="$2"
    [[ "${value}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || die "${kind} inválido: '${value}'."
}

select_installation_profile() {
    section "Perfil deste node"
    cat <<'EOF_ROLES'
O Capivara pode trabalhar em três papéis:

  controller
    Central de gerenciamento. Mantém painel, controle e orquestração.
    Normalmente NÃO executa servidores de jogos e não precisa de SteamCMD.

  agent
    Máquina de execução. Recebe tarefas do Controller e hospeda instâncias
    de jogos. Dependências de jogos, como SteamCMD, pertencem a este node.

  hybrid
    Controller e Agent na mesma máquina. Indicado para laboratório,
    ambientes pequenos ou instalação tudo-em-um. Pode executar jogos localmente.
EOF_ROLES

    printf '\nConta de serviço:\n'
    printf '  O usuário/grupo abaixo será usado pelos serviços do Capivara e para\n'
    printf '  controlar os diretórios graváveis. O padrão é o usuário atual da máquina.\n\n'

    prompt_value DSM_SERVICE_USER "Usuário de serviço" "${DEFAULT_SERVICE_USER}"
    prompt_value DSM_SERVICE_GROUP "Grupo de serviço" "${DEFAULT_SERVICE_GROUP}"
    prompt_value DSM_NODE_ROLE "Papel deste node (controller/agent/hybrid)" "${DEFAULT_NODE_ROLE}"

    validate_account_name "${DSM_SERVICE_USER}" "Usuário"
    validate_account_name "${DSM_SERVICE_GROUP}" "Grupo"
    case "${DSM_NODE_ROLE}" in controller|agent|hybrid) ;; *) die "Papel inválido: '${DSM_NODE_ROLE}'." ;; esac
}

show_plan() {
    section "Resumo antes da instalação"
    printf 'Origem do pacote : %s\n' "${INSTALL_MODE}"
    [[ "${INSTALL_MODE}" == "remote" ]] && printf 'Release           : %s\n' "${CAPIVARA_RELEASE_TAG}"
    printf 'Papel do node     : %s\n' "${DSM_NODE_ROLE}"
    printf 'Conta de serviço  : %s:%s\n' "${DSM_SERVICE_USER}" "${DSM_SERVICE_GROUP}"
    printf 'Diretório         : %s\n' "${DSM_ROOT}"
    if [[ "${ALLOW_REINSTALL}" -eq 1 ]]
    then
        printf 'Reinstalação    : SIM (sem backup e rollback)\n'
    fi
    if [[ "${DSM_NODE_ROLE}" == "controller" ]]; then
        printf 'SteamCMD          : não aplicável ao Controller\n'
    else
        printf 'SteamCMD          : %s\n' "${INSTALL_STEAMCMD}"
    fi

    if is_interactive; then
        printf '\nO instalador poderá criar usuário/grupo, instalar pacotes do sistema e\n'
        printf 'registrar unidades systemd.\n'
        local answer
        read -r -p "Continuar com esta configuração? [S/n]: " answer
        case "${answer:-s}" in s|S|sim|SIM|y|Y|yes|YES) ;; *) die "Instalação cancelada pelo usuário." ;; esac
    fi
}

detect_package_manager() {
    if command -v apt-get >/dev/null 2>&1; then PKG_MANAGER="apt"
    elif command -v dnf >/dev/null 2>&1; then PKG_MANAGER="dnf"
    elif command -v yum >/dev/null 2>&1; then PKG_MANAGER="yum"
    elif command -v zypper >/dev/null 2>&1; then PKG_MANAGER="zypper"
    elif command -v pacman >/dev/null 2>&1; then PKG_MANAGER="pacman"
    else PKG_MANAGER=""; fi
}

install_packages() {
    local packages=("$@"); ((${#packages[@]})) || return 0
    [[ -n "${PKG_MANAGER}" ]] || die "Nenhum gerenciador de pacotes suportado foi encontrado."
    log "Instalando dependências faltantes: ${packages[*]}"
    case "${PKG_MANAGER}" in
        apt)
            if [[ "${APT_UPDATED:-0}" != "1" ]]; then DEBIAN_FRONTEND=noninteractive apt-get update; APT_UPDATED=1; fi
            DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}" ;;
        dnf) dnf install -y "${packages[@]}" ;; yum) yum install -y "${packages[@]}" ;;
        zypper) zypper --non-interactive install "${packages[@]}" ;;
        pacman) pacman -Sy --noconfirm --needed "${packages[@]}" ;;
    esac
}

ensure_command() {
    local command_name="$1"; shift
    command -v "${command_name}" >/dev/null 2>&1 && return 0
    local package=""
    case "${PKG_MANAGER}" in
        apt) package="${1:-}" ;; dnf|yum) package="${2:-${1:-}}" ;;
        zypper) package="${3:-${2:-${1:-}}}" ;; pacman) package="${4:-${3:-${2:-${1:-}}}}" ;;
    esac
    [[ -n "${package}" ]] || die "Dependência '${command_name}' ausente e sem pacote conhecido."
    install_packages "${package}"
    command -v "${command_name}" >/dev/null 2>&1 || die "Falha ao instalar '${command_name}'."
}

ensure_base_dependencies() {
    section "Dependências básicas"
    explain "Vou verificar as ferramentas usadas pelo instalador e pelo núcleo do Capivara. Só os pacotes ausentes serão instalados."
    detect_package_manager
    ensure_command bash bash bash bash bash
    ensure_command rsync rsync rsync rsync rsync
    ensure_command curl curl curl curl curl
    ensure_command tar tar tar tar tar
    ensure_command python3 python3 python3 python3 python
    ensure_command systemctl systemd systemd systemd systemd
    ensure_command getent libc-bin glibc glibc glibc
    ensure_command sha256sum coreutils coreutils coreutils coreutils
}

github_headers() {
    printf '%s\n' "-H" "Accept: application/vnd.github+json" "-H" "X-GitHub-Api-Version: 2026-03-10"
    [[ -n "${GH_TOKEN}" ]] && printf '%s\n' "-H" "Authorization: Bearer ${GH_TOKEN}"
}

github_api_get() { local -a args=(); mapfile -t args < <(github_headers); curl -fsSL "${args[@]}" "$1"; }
download_with_github_auth() { local -a args=(); mapfile -t args < <(github_headers); curl -fL --retry 3 --retry-delay 2 "${args[@]}" -o "$2" "$1"; }
cleanup_bootstrap() { [[ -n "${BOOTSTRAP_TMP}" && -d "${BOOTSTRAP_TMP}" ]] && rm -rf "${BOOTSTRAP_TMP}" || true; }

release_metadata() {
    local endpoint
    if [[ "${CAPIVARA_RELEASE_TAG}" == "latest" ]]; then endpoint="${CAPIVARA_GITHUB_API}/repos/${CAPIVARA_GITHUB_REPO}/releases/latest"
    else endpoint="${CAPIVARA_GITHUB_API}/repos/${CAPIVARA_GITHUB_REPO}/releases/tags/${CAPIVARA_RELEASE_TAG}"; fi
    if ! github_api_get "${endpoint}"; then
        [[ -z "${GH_TOKEN}" ]] && die "Não foi possível consultar a release. Se o repositório for privado, informe GH_TOKEN."
        die "Não foi possível consultar a release '${CAPIVARA_RELEASE_TAG}'."
    fi
}

acquire_remote_source() {
    section "Origem da instalação"
    explain "Vou consultar o GitHub Releases, baixar a versão escolhida em um diretório temporário e validar o pacote antes de instalar."
    BOOTSTRAP_TMP="$(mktemp -d -t capivara-installer.XXXXXX)"; trap cleanup_bootstrap EXIT
    local metadata_file="${BOOTSTRAP_TMP}/release.json"; release_metadata > "${metadata_file}"

    local release_info
    release_info="$(python3 - "${metadata_file}" <<'PY_RELEASE'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f: data=json.load(f)
tag=data.get("tag_name", ""); tarball=data.get("tarball_url", ""); assets=data.get("assets", []); selected=None
for asset in assets:
    name=asset.get("name", "").lower()
    if name.endswith(".tar.gz") and ("capivara" in name or "dsm" in name): selected=asset; break
if selected is None:
    for asset in assets:
        if asset.get("name", "").lower().endswith(".tar.gz"): selected=asset; break
if selected:
    print(tag); print(selected.get("url", "")); print(selected.get("digest", "")); print("asset")
else:
    print(tag); print(tarball); print(""); print("tarball")
PY_RELEASE
)"
    local tag download_url digest source_kind
    tag="$(sed -n '1p' <<<"${release_info}")"; download_url="$(sed -n '2p' <<<"${release_info}")"
    digest="$(sed -n '3p' <<<"${release_info}")"; source_kind="$(sed -n '4p' <<<"${release_info}")"
    [[ -n "${tag}" && -n "${download_url}" ]] || die "A release não contém pacote utilizável."

    local archive="${BOOTSTRAP_TMP}/capivara-${tag}.tar.gz"; log "Baixando Capivara DSM ${tag}."
    if [[ "${source_kind}" == "asset" ]]; then
        local -a args=(); mapfile -t args < <(github_headers)
        curl -fL --retry 3 --retry-delay 2 "${args[@]}" -H "Accept: application/octet-stream" -o "${archive}" "${download_url}"
    else download_with_github_auth "${download_url}" "${archive}"; fi

    [[ -s "${archive}" ]] || die "O pacote baixado está vazio."
    if [[ "${digest}" == sha256:* ]]; then
        local expected actual; expected="${digest#sha256:}"; actual="$(sha256sum "${archive}" | awk '{print $1}')"
        [[ "${actual}" == "${expected}" ]] || die "Falha na validação SHA-256 da release ${tag}."; log "Checksum SHA-256 validado."
    else warn "Release sem digest SHA-256; validando a integridade do tar.gz."; fi

    tar -tzf "${archive}" >/dev/null || die "Pacote corrompido ou inválido."
    local extract_dir="${BOOTSTRAP_TMP}/source"; mkdir -p "${extract_dir}"; tar -xzf "${archive}" -C "${extract_dir}"
    if [[ -f "${extract_dir}/bin/dsm" ]]; then DSM_SOURCE="${extract_dir}"
    else
        local candidate; candidate="$(find "${extract_dir}" -mindepth 1 -maxdepth 3 -type f -path '*/bin/dsm' -print -quit)"
        [[ -n "${candidate}" ]] || die "O pacote da release não contém bin/dsm."
        DSM_SOURCE="$(dirname "$(dirname "${candidate}")")"
    fi
    log "Release ${tag} preparada para instalação."
}

acquire_source() {
    if [[ "${INSTALL_MODE}" == "local" ]]; then
        section "Origem da instalação"
        explain "Modo local selecionado. Vou usar os arquivos que estão ao lado deste install.sh, sem baixar o projeto do GitHub."
        DSM_SOURCE="${INSTALLER_DIR}"; log "Usando arquivos em ${DSM_SOURCE}."
    else acquire_remote_source; fi
}

ensure_service_account() {
    section "Conta de serviço"
    explain "Vou garantir que o usuário e o grupo escolhidos existam. Eles isolam os serviços do Capivara de contas pessoais do servidor."
    if ! getent group "${DSM_SERVICE_GROUP}" >/dev/null 2>&1; then log "Criando grupo '${DSM_SERVICE_GROUP}'."; groupadd --system "${DSM_SERVICE_GROUP}"; fi
    if ! id "${DSM_SERVICE_USER}" >/dev/null 2>&1; then
        log "Criando usuário '${DSM_SERVICE_USER}'."; useradd --system --gid "${DSM_SERVICE_GROUP}" --home-dir "${DSM_ROOT}" --shell /usr/sbin/nologin "${DSM_SERVICE_USER}"
    else
        local primary_group; primary_group="$(id -gn "${DSM_SERVICE_USER}")"
        if [[ "${primary_group}" != "${DSM_SERVICE_GROUP}" ]]; then warn "Usuário existente com outro grupo primário; adicionando ao grupo '${DSM_SERVICE_GROUP}'."; usermod -a -G "${DSM_SERVICE_GROUP}" "${DSM_SERVICE_USER}"; fi
    fi
    DSM_SERVICE_HOME="$(getent passwd "${DSM_SERVICE_USER}" | cut -d: -f6)"
    [[ -n "${DSM_SERVICE_HOME}" ]] || die "Não foi possível determinar o home de '${DSM_SERVICE_USER}'."
}

local_source_available() {
    [[ -f "${INSTALLER_DIR}/bin/dsm" ]] \
        && [[ -f "${INSTALLER_DIR}/core/bootstrap.sh" ]] \
        && [[ -f "${INSTALLER_DIR}/config/dsm.conf" ]]
}

select_installation_source() {
    [[ "${INSTALL_MODE_EXPLICIT}" -eq 0 ]] || return 0
    is_interactive || return 0

    section "Origem da instalação"
    if local_source_available
    then
        cat <<'EOF_SOURCE'
Escolha a origem dos arquivos:

  1) Arquivos locais ao lado deste install.sh
  2) Release publicada no GitHub

Use a opção local quando ainda não existir uma release publicada.
EOF_SOURCE
        local source_choice
        read -r -p "Origem [1]: " source_choice
        case "${source_choice:-1}" in
            1|local) INSTALL_MODE="local" ;;
            2|remote|github) INSTALL_MODE="remote" ;;
            *) die "Origem inválida: ${source_choice}." ;;
        esac
    else
        INSTALL_MODE="remote"
        printf '\nArquivos locais incompletos; será usada uma release do GitHub.\n'
    fi
}

verify_source_tree() {
    section "Validação do pacote"
    explain "Vou confirmar se os arquivos essenciais existem antes de alterar /opt/dsm. Isso evita uma instalação parcial ou quebrada."
    local required=("version" "bin/dsm" "core/bootstrap.sh" "server/server.sh" "config/dsm.conf" "database/manager.py" "database/migrations/001_initial.sql" "systemd/dsm-monitor.service" "systemd/dsm-scheduler.service" "systemd/dsm-dashboard.service") missing=() path
    for path in "${required[@]}"; do [[ -e "${DSM_SOURCE}/${path}" ]] || missing+=("${path}"); done
    if ((${#missing[@]})); then printf '[Capivara][ERRO] Arquivos ausentes:\n' >&2; printf '  - %s\n' "${missing[@]}" >&2; die "A origem selecionada não contém uma distribuição completa."; fi
    log "Estrutura mínima validada."
}

read_package_version() {
    local version_file="$1" value=""
    if [[ -f "${version_file}" ]]
    then
        IFS= read -r value <"${version_file}" || true
    fi
    printf '%s' "${value:-desconhecida}"
}

guard_existing_installation() {
    local installed_version package_version

    if [[ ! -f "${DSM_ROOT}/version" ]] \
        && [[ ! -f "${DSM_ROOT}/config/dsm.conf" ]] \
        && [[ ! -x "${DSM_ROOT}/bin/dsm" ]]
    then
        return 0
    fi

    installed_version="$(read_package_version "${DSM_ROOT}/version")"
    package_version="$(read_package_version "${DSM_SOURCE}/version")"

    if [[ "${ALLOW_REINSTALL}" -eq 1 ]]
    then
        warn "Reinstalação explícita: ${installed_version} -> ${package_version}. Não haverá backup ou rollback."
        return 0
    fi

    cat >&2 <<EOF_EXISTING

==============================================================
 INSTALAÇÃO EXISTENTE DETECTADA
==============================================================

Diretório         : ${DSM_ROOT}
Versão instalada  : ${installed_version}
Versão do pacote : ${package_version}

O install.sh não sobrescreve uma instalação existente.
Use o update.sh do novo pacote para atualizar com backup e rollback:

  sudo ./update.sh /caminho/do/novo-pacote

Para uma reinstalação intencional sem proteção transacional,
execute novamente com --reinstall.
EOF_EXISTING
    exit 1
}

install_project_files() {
    section "Arquivos do Capivara"
    explain "Vou copiar/atualizar o projeto em /opt/dsm, ajustar executáveis e preparar diretórios de cache, logs, dados, runtime e instâncias."
    mkdir -p "${DSM_ROOT}/config"
    rsync -a \
        --exclude "install.sh" \
        --exclude "config/dsm.conf" \
        --exclude "config/agent.conf" \
        "${DSM_SOURCE}/" "${DSM_ROOT}/"
    if [[ ! -f "${DSM_ROOT}/config/dsm.conf" ]]
    then
        cp "${DSM_SOURCE}/config/dsm.conf" "${DSM_ROOT}/config/dsm.conf"
    fi
    find "${DSM_ROOT}" -type d -exec chmod 755 {} \;; find "${DSM_ROOT}" -type f -name "*.sh" -exec chmod +x {} \;; chmod +x "${DSM_BIN}"
    mkdir -p "${DSM_ROOT}/cache" "${DSM_ROOT}/logs" "${DSM_ROOT}/tmp" "${DSM_ROOT}/data" "${DSM_ROOT}/runtime" "${DSM_ROOT}/instances"
    chown -R "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" "${DSM_ROOT}/cache" "${DSM_ROOT}/logs" "${DSM_ROOT}/tmp" "${DSM_ROOT}/data" "${DSM_ROOT}/runtime" "${DSM_ROOT}/instances"
}

set_shell_config_value() {
    local file="$1" key="$2" value="$3" escaped
    [[ "${value}" != *$'\n'* && "${value}" != *'"'* ]] || die "Valor inválido para ${key}."
    escaped="${value//\\/\\\\}"
    escaped="${escaped//&/\\&}"
    escaped="${escaped//|/\\|}"
    if grep -q "^${key}=" "${file}"
    then
        sed -i "s|^${key}=.*|${key}=\"${escaped}\"|" "${file}"
    else
        printf '%s="%s"\n' "${key}" "${value}" >>"${file}"
    fi
}

write_dsm_config() {
    local config_file="${DSM_ROOT}/config/dsm.conf"
    local installed_version="unknown"
    section "Configuração principal"
    explain "Vou registrar no dsm.conf a mesma conta de serviço escolhida para o Agent e para o systemd."
    [[ -f "${config_file}" ]] || die "Configuração principal ausente: ${config_file}"
    if [[ -s "${DSM_ROOT}/version" ]]
    then
        installed_version=$(tr -d '\r\n' <"${DSM_ROOT}/version")
    fi
    set_shell_config_value "${config_file}" DSM_VERSION "${installed_version}"
    set_shell_config_value "${config_file}" INSTALLER_VERSION "${installed_version}"
    set_shell_config_value "${config_file}" DSM_DATA_DIR "${DSM_ROOT}/data"
    set_shell_config_value "${config_file}" DSM_DATABASE "${DSM_ROOT}/data/capivara.db"
    set_shell_config_value "${config_file}" DSM_USER "${DSM_SERVICE_USER}"
    set_shell_config_value "${config_file}" DSM_GROUP "${DSM_SERVICE_GROUP}"
    set_shell_config_value "${config_file}" DSM_HOME "${DSM_SERVICE_HOME}"
    chown "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" "${config_file}"
    chmod 640 "${config_file}"
}

initialize_database() {
    local manager="${DSM_ROOT}/database/manager.py"
    local database="${DSM_ROOT}/data/capivara.db"
    section "Banco de dados"
    explain "Vou criar o banco SQLite local e aplicar somente as migrações ainda pendentes."
    [[ -f "${manager}" ]] || die "Gerenciador de banco ausente: ${manager}"
    python3 "${manager}" --root "${DSM_ROOT}" --database "${database}" init
    chown -R "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" "${DSM_ROOT}/data"
    chmod 750 "${DSM_ROOT}/data"
    chmod 640 "${database}"
}

write_agent_config() {
    section "Configuração do node"
    explain "Vou registrar o papel deste servidor, a conta de serviço, o diretório de instâncias e o caminho do SteamCMD. Configurações existentes serão preservadas quando possível."
    mkdir -p "${DSM_ROOT}/config"
    if [[ ! -f "${DSM_ROOT}/config/agent.conf" ]]; then
        cat > "${DSM_ROOT}/config/agent.conf" <<EOF_AGENT
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
        sed -i -e "s|^DSM_NODE_ROLE=.*|DSM_NODE_ROLE=\"${DSM_NODE_ROLE}\"|" -e "s|^DSM_USER=.*|DSM_USER=\"${DSM_SERVICE_USER}\"|" -e "s|^DSM_GROUP=.*|DSM_GROUP=\"${DSM_SERVICE_GROUP}\"|" "${DSM_ROOT}/config/agent.conf"
        grep -q '^DSM_NODE_ROLE=' "${DSM_ROOT}/config/agent.conf" || printf 'DSM_NODE_ROLE="%s"\n' "${DSM_NODE_ROLE}" >> "${DSM_ROOT}/config/agent.conf"
        grep -q '^DSM_USER=' "${DSM_ROOT}/config/agent.conf" || printf 'DSM_USER="%s"\n' "${DSM_SERVICE_USER}" >> "${DSM_ROOT}/config/agent.conf"
        grep -q '^DSM_GROUP=' "${DSM_ROOT}/config/agent.conf" || printf 'DSM_GROUP="%s"\n' "${DSM_SERVICE_GROUP}" >> "${DSM_ROOT}/config/agent.conf"
        grep -q '^STEAMCMD_ROOT=' "${DSM_ROOT}/config/agent.conf" || printf 'STEAMCMD_ROOT="%s"\n' "${STEAMCMD_ROOT}" >> "${DSM_ROOT}/config/agent.conf"
    fi
    chown "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" "${DSM_ROOT}/config/agent.conf"; chmod 640 "${DSM_ROOT}/config/agent.conf"
}

install_cli() {
    section "Comando dsm"
    explain "Vou registrar /usr/local/bin/dsm para que o Capivara possa ser chamado pelo terminal sem informar o caminho completo."
    ln -sf "${DSM_BIN}" "${DSM_LINK}"; chmod +x "${DSM_LINK}"; hash -r || true
}

install_systemd_units() {
    [[ -d "${DSM_ROOT}/systemd" ]] || return 0
    section "Serviços systemd"
    explain "Vou instalar as unidades de serviço, aplicar a conta escolhida e habilitar os componentes principais para inicialização com o sistema."
    local source_unit unit_name destination
    while IFS= read -r -d '' source_unit; do
        unit_name="$(basename "${source_unit}")"; destination="${SYSTEMD_DIR}/${unit_name}"; cp -f "${source_unit}" "${destination}"
        sed -i \
            -e "s|{{DSM_USER}}|${DSM_SERVICE_USER}|g" \
            -e "s|{{DSM_GROUP}}|${DSM_SERVICE_GROUP}|g" \
            "${destination}"
    done < <(find "${DSM_ROOT}/systemd" -maxdepth 1 -type f \( -name '*.service' -o -name '*.timer' \) -print0)
    systemctl daemon-reload
    local core_units=(dsm-monitor.service dsm-scheduler.service dsm-alert-engine.service dsm-dashboard.service dsm-dashboard-worker.service dsm-notification-engine.timer dsm-notification-center.timer) unit
    for unit in "${core_units[@]}"; do [[ -f "${SYSTEMD_DIR}/${unit}" ]] && systemctl enable "${unit}"; done
    local legacy_worker_units=(dsm-backup-worker.service dsm-events-worker.service dsm-metrics-worker.service dsm-mods-worker.service dsm-server-worker.service)
    for unit in "${legacy_worker_units[@]}"; do
        [[ -f "${SYSTEMD_DIR}/${unit}" ]] && systemctl disable --now "${unit}" 2>/dev/null || true
    done
}

should_install_steamcmd() {
    case "${INSTALL_STEAMCMD}" in
        1|yes|true) return 0 ;; 0|no|false) return 1 ;;
        auto)
            [[ "${DSM_NODE_ROLE}" == "agent" || "${DSM_NODE_ROLE}" == "hybrid" ]] || return 1
            if is_interactive; then
                printf '\nSteamCMD é usado por jogos distribuídos pela Steam. Ele fica no Agent,\nporque é o Agent que instala e atualiza os servidores de jogo.\n'
                local answer; read -r -p "Instalar/verificar SteamCMD neste node? [S/n]: " answer
                case "${answer:-s}" in s|S|sim|SIM|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
            fi
            return 0 ;;
        *) die "DSM_INSTALL_STEAMCMD inválido: '${INSTALL_STEAMCMD}'." ;;
    esac
}

install_steamcmd() {
    section "Dependências de jogos"
    if [[ "${DSM_NODE_ROLE}" == "controller" ]]; then
        explain "Este node é Controller. Ele orquestra o ambiente, mas não precisa do SteamCMD para executar sua função."
        log "SteamCMD não será instalado."; return 0
    fi
    explain "Este node executa a função Agent. Vou verificar o SteamCMD, necessário para provisionar jogos que usam a Steam."
    if command -v steamcmd >/dev/null 2>&1; then log "SteamCMD já disponível em $(command -v steamcmd)."; return 0; fi
    should_install_steamcmd || { warn "SteamCMD não instalado; jogos dependentes dele ficarão indisponíveis até a dependência ser adicionada."; return 0; }
    log "Instalando SteamCMD em ${STEAMCMD_ROOT}."; mkdir -p "${STEAMCMD_ROOT}"
    curl -fsSL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" | tar -xz -C "${STEAMCMD_ROOT}"
    [[ -x "${STEAMCMD_ROOT}/steamcmd.sh" ]] || die "steamcmd.sh não encontrado após download."
    chown -R "${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}" "${STEAMCMD_ROOT}"; ln -sf "${STEAMCMD_ROOT}/steamcmd.sh" /usr/local/bin/steamcmd
}

validate_installation() {
    section "Verificação final"
    explain "Vou conferir o comando principal e as unidades essenciais. Se algo básico estiver faltando, a instalação será marcada como falha."
    command -v dsm >/dev/null 2>&1 || die "Comando dsm não encontrado após instalação."
    [[ -x "${DSM_BIN}" ]] || die "CLI DSM não está executável: ${DSM_BIN}"
    python3 "${DSM_ROOT}/database/manager.py" --root "${DSM_ROOT}" check >/dev/null \
        || die "Banco de dados ausente ou inválido após instalação."
    local unit; for unit in dsm-monitor.service dsm-scheduler.service dsm-dashboard.service; do [[ -f "${SYSTEMD_DIR}/${unit}" ]] || die "Unidade systemd ausente: ${unit}"; done
    log "Validação básica concluída."
}

main() {
    parse_args "$@"; require_root; show_banner; show_welcome
    select_installation_source; select_installation_profile; show_plan
    ensure_base_dependencies; acquire_source; verify_source_tree; guard_existing_installation; ensure_service_account
    install_project_files; write_dsm_config; write_agent_config; initialize_database; install_cli; install_systemd_units; install_steamcmd; validate_installation

    section "Capivara DSM instalado com sucesso"
    printf 'Origem            : %s\n' "${INSTALL_MODE}"
    printf 'Node              : %s\n' "${DSM_NODE_ROLE}"
    printf 'Conta de serviço  : %s:%s\n' "${DSM_SERVICE_USER}" "${DSM_SERVICE_GROUP}"
    printf 'Comando           : %s\n' "$(command -v dsm)"
    if [[ "${DSM_NODE_ROLE}" == "agent" || "${DSM_NODE_ROLE}" == "hybrid" ]]; then
        printf 'SteamCMD          : %s\n' "$(command -v steamcmd 2>/dev/null || echo 'não instalado')"
    else
        printf 'SteamCMD          : não aplicável ao Controller\n'
    fi
    show_credits
    printf '\n'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    main "$@"
fi
