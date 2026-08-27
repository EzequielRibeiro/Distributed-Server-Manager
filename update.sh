#!/usr/bin/env bash
# =============================================================
# DSM Update Manager
#
# Atualização segura do Capivara Distributed Server Manager
# Safe update of Capivara Distributed Server Manager
#
# Recursos: | Features:
# - valida pacote DSM | validates DSM package
# - backup automático | automatic backup
# - staging temporário | temporary staging
# - rollback automático | automatic rollback
# - preserva dados do usuário | preserves user data
# - atualiza systemd | updates systemd
# - valida instalação final | validates final installation
#
# Uso: | Usage:
#
# sudo ./update.sh /caminho/DSM-nova-versao
# sudo ./update.sh /path/DSM-new-version
#
# Opções: | Options:
#
# --yes                 atualização automática | automatic update
# --allow-same-version  permite reinstalar a mesma versão | allows reinstalling the same version
# --allow-downgrade     permite instalar uma versão anterior | allows installing an older version
#
# =============================================================
# A versão é lida do arquivo version na raiz do pacote.

set -Eeuo pipefail

#############################################
# Versão do Update Manager
# Update Manager Version
#############################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -s "${SCRIPT_DIR}/version" ]]
then
    VERSION=$(tr -d '\r\n' <"${SCRIPT_DIR}/version")
else
    VERSION="unknown"
fi

#############################################
# Diretórios principais
# Main directories
#############################################
INSTALL_DIR="/opt/dsm"
CONFIG_FILE="${INSTALL_DIR}/config/dsm.conf"
BACKUP_DIR="/opt/dsm-backups"
STAGING_DIR="/opt/dsm-update-stage"
SYSTEMD_DIR="/etc/systemd/system"
BIN_LINK="/usr/local/bin/dsm"
CAP_LINK="/usr/local/bin/cap"

#############################################
# Usuário DSM | DSM User
#
# Será carregado do dsm.conf
# Will be loaded from dsm.conf
#############################################
DSM_USER=""
DSM_GROUP=""
DSM_HOME=""

#############################################
# Configuração DSM | DSM Configuration
#############################################
DSM_VERSION=""
INSTALLER_VERSION=""
DSM_DATA_DIR=""
DSM_DATABASE=""
DSM_DATABASE_DRIVER="sqlite"
DSM_DATABASE_HOST=""
DSM_DATABASE_PORT=""
DSM_DATABASE_NAME="capivara"
DSM_DATABASE_USER=""
DSM_DATABASE_PASSWORD_FILE=""
DSM_DATABASE_TLS="preferred"
INSTALL_LOG=""
INSTALL_DATE=""
SYSTEMD_ENABLED=1
DASHBOARD_ENABLED=1

#############################################
# Controle de execução | Execution control
#############################################
AUTO_YES=0
ALLOW_SAME_VERSION=0
ALLOW_DOWNGRADE=0
NO_BACKUP=0
NEW_SRC=""
BACKUP_FILE=""
BACKUP_PART=""
BACKUP_PROCESS_PID=""
DATABASE_BACKUP_FILE=""
UPDATE_TRANSACTION_STARTED=0
ACTIVE_SERVICES=()
STOP_SERVICES=()
RESTORE_SERVICES=()
DISCOVERED_SERVICES=()
SERVICE_ACTIVE_STATES=()
SERVICE_SUB_STATES=()
SERVICE_UNIT_STATES=()
SERVICE_TYPES=()
SERVICE_RESTART_POLICIES=()
READINESS_TIMEOUT="${DSM_UPDATE_READINESS_TIMEOUT:-60}"
READINESS_INTERVAL="${DSM_UPDATE_READINESS_INTERVAL:-2}"
OLD_VERSION=""
NEW_VERSION=""

print_usage() {
    cat <<'EOF_USAGE'
Usage: sudo ./update.sh [options] /path/DSM-new-version

Options:
  --yes                 Run without the interactive confirmation.
  --allow-same-version  Allow reinstalling the currently installed version.
  --allow-downgrade     Allow installing an older version.
  --no-backup           Skip the pre-update backup. Automatic rollback will not be available.
  -h, --help            Show this help message.
EOF_USAGE
}

parse_arguments() {
    while [[ $# -gt 0 ]]
    do
        case "$1" in
            --yes)
                AUTO_YES=1
                ;;
            --allow-same-version)
                ALLOW_SAME_VERSION=1
                ;;
            --allow-downgrade)
                ALLOW_DOWNGRADE=1
                ;;
            --no-backup)
                NO_BACKUP=1
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            --)
                shift
                break
                ;;
            -*)
                echo "Unknown option: $1" >&2
                print_usage >&2
                exit 2
                ;;
            *)
                if [[ -n "${NEW_SRC}" ]]
                then
                    echo "Only one DSM package directory may be specified." >&2
                    print_usage >&2
                    exit 2
                fi
                NEW_SRC="$1"
                ;;
        esac
        shift
    done

    if [[ $# -gt 0 ]]
    then
        if [[ -n "${NEW_SRC}" || $# -gt 1 ]]
        then
            echo "Only one DSM package directory may be specified." >&2
            print_usage >&2
            exit 2
        fi
        NEW_SRC="$1"
    fi
}

#############################################
# Logs
#############################################
LOG_DIR="${INSTALL_DIR}/logs"
INSTALL_LOG="${LOG_DIR}/update.log"

initialize_logging() {
    mkdir -p "${LOG_DIR}"
    exec > >(tee -a "${INSTALL_LOG}")
    exec 2>&1
}


# =============================================================
# Migração de conta de runtime para instalações legadas
# Legacy runtime account migration
# =============================================================

resolve_legacy_runtime_account() {
    local detected_user=""
    local detected_group=""
    local detected_home=""

    if [[ -z "${DSM_USER:-}" ]]
    then
        detected_user=$(stat -c '%U' "${INSTALL_DIR}" 2>/dev/null || true)

        if [[ -n "${detected_user}" && "${detected_user}" != "root" ]]
        then
            DSM_USER="${detected_user}"

            echo
            echo "DSM_USER legado detectado automaticamente:"
            echo "${DSM_USER}"
        fi
    fi

    if [[ -n "${DSM_USER:-}" && -z "${DSM_GROUP:-}" ]]
    then
        detected_group=$(id -gn "${DSM_USER}" 2>/dev/null || true)

        if [[ -n "${detected_group}" ]]
        then
            DSM_GROUP="${detected_group}"

            echo
            echo "DSM_GROUP legado detectado automaticamente:"
            echo "${DSM_GROUP}"
        fi
    fi

    if [[ -n "${DSM_USER:-}" && -z "${DSM_HOME:-}" ]]
    then
        detected_home=$(
            getent passwd "${DSM_USER}" 2>/dev/null |
                cut -d: -f6
        )

        if [[ -n "${detected_home}" ]]
        then
            DSM_HOME="${detected_home}"

            echo
            echo "DSM_HOME legado detectado automaticamente:"
            echo "${DSM_HOME}"
        fi
    fi
}

# =============================================================
# Carregar configuração DSM existente
# Load existing DSM configuration
# =============================================================
load_configuration() {
    if [[ ! -f "${CONFIG_FILE}" ]]
    then
        echo
        echo "Configuração DSM não encontrada."
        echo "DSM configuration not found."
        exit 1
    fi
    echo
    echo "Carregando configuração DSM..."
    echo "Loading DSM configuration..."
    source "${CONFIG_FILE}"

    resolve_legacy_runtime_account

    export DSM_DATABASE_DRIVER DSM_DATABASE DSM_DATABASE_HOST DSM_DATABASE_PORT
    export DSM_DATABASE_NAME DSM_DATABASE_USER DSM_DATABASE_PASSWORD_FILE
    export DSM_DATABASE_TLS
    if [[ -z "${DSM_USER:-}" ]]
    then
        echo "Usuário DSM não definido."
        echo "DSM user not defined."
        exit 1
    fi
    if [[ -z "${DSM_GROUP:-}" ]]
    then
        DSM_GROUP="${DSM_USER}"
    fi
    echo
    echo "Usuário | User DSM:"
    echo "${DSM_USER}"
    echo "Grupo | Group DSM:"
    echo "${DSM_GROUP}"
}

# =============================================================
# Validar conta de execução | Validate runtime account
# =============================================================
validate_runtime_account() {
    local ACCOUNT_HOME

    echo
    echo "Validando conta de execução DSM..."
    echo "Validating DSM runtime account..."

    if ! id -u "${DSM_USER}" >/dev/null 2>&1
    then
        echo
        echo "ERRO: usuário DSM inexistente: ${DSM_USER}"
        echo "ERROR: DSM user does not exist: ${DSM_USER}"
        echo "Corrija DSM_USER em ${CONFIG_FILE} antes de atualizar."
        echo "Correct DSM_USER in ${CONFIG_FILE} before updating."
        exit 1
    fi

    if ! getent group "${DSM_GROUP}" >/dev/null 2>&1
    then
        echo
        echo "ERRO: grupo DSM inexistente: ${DSM_GROUP}"
        echo "ERROR: DSM group does not exist: ${DSM_GROUP}"
        echo "Corrija DSM_GROUP em ${CONFIG_FILE} antes de atualizar."
        echo "Correct DSM_GROUP in ${CONFIG_FILE} before updating."
        exit 1
    fi

    if [[ -z "${DSM_HOME:-}" ]]
    then
        echo
        echo "ERRO: DSM_HOME não definido."
        echo "ERROR: DSM_HOME is not defined."
        echo "Corrija DSM_HOME em ${CONFIG_FILE} antes de atualizar."
        echo "Correct DSM_HOME in ${CONFIG_FILE} before updating."
        exit 1
    fi

    if [[ ! -d "${DSM_HOME}" ]]
    then
        echo
        echo "ERRO: diretório DSM_HOME inexistente: ${DSM_HOME}"
        echo "ERROR: DSM_HOME directory does not exist: ${DSM_HOME}"
        echo "Corrija DSM_HOME em ${CONFIG_FILE} antes de atualizar."
        echo "Correct DSM_HOME in ${CONFIG_FILE} before updating."
        exit 1
    fi

    ACCOUNT_HOME=$(getent passwd "${DSM_USER}" | cut -d: -f6) || ACCOUNT_HOME=""
    if [[ -n "${ACCOUNT_HOME}" ]] && [[ "${ACCOUNT_HOME}" != "${DSM_HOME}" ]]
    then
        echo
        echo "AVISO: DSM_HOME difere do home cadastrado para ${DSM_USER}."
        echo "WARNING: DSM_HOME differs from the registered home for ${DSM_USER}."
        echo "DSM_HOME: ${DSM_HOME}"
        echo "Home da conta | Account home: ${ACCOUNT_HOME}"
    fi

    echo "Conta DSM válida | DSM account is valid."
}

# =============================================================
# Validar pacote de atualização
# Validate update package
# =============================================================
validate_package() {
    echo
    echo "Validando pacote DSM..."
    echo "Validating DSM package..."
    REQUIRED_FILES=(
        "version"
        "bin/dsm"
        "bin/cap"
        "core/bootstrap.sh"
    )
    for FILE in "${REQUIRED_FILES[@]}"
    do
        if [[ ! -e "${NEW_SRC}/${FILE}" ]]
        then
            echo
            echo "Arquivo obrigatório ausente:"
            echo "Required file missing:"
            echo "${FILE}"
            exit 1
        fi
    done
    echo
    echo "Pacote válido."
    echo "Valid package."
}

# =============================================================
# Ler versões | Read versions
# =============================================================
read_versions() {
    echo
    if [[ -f "${INSTALL_DIR}/version" ]]
    then
        OLD_VERSION=$(cat "${INSTALL_DIR}/version")
    else
        OLD_VERSION="unknown"
    fi
    NEW_VERSION=$(cat "${NEW_SRC}/version")
    echo "Versão atual | Current version:"
    echo "${OLD_VERSION}"
    echo
    echo "Nova versão | New version:"
    echo "${NEW_VERSION}"
}

# =============================================================
# Política de versão semântica | Semantic version policy
# =============================================================
SEMVER_LIB="${SCRIPT_DIR}/core/semver.sh"

if [[ ! -f "${SEMVER_LIB}" ]]
then
    echo "ERRO: biblioteca SemVer não encontrada: ${SEMVER_LIB}" >&2
    echo "ERROR: SemVer library not found: ${SEMVER_LIB}" >&2
    exit 1
fi

# shellcheck source=core/semver.sh
source "${SEMVER_LIB}"

enforce_version_policy() {
    local COMPARISON

    if ! is_semver "${NEW_VERSION}"
    then
        echo "ERRO: versão do novo pacote não segue SemVer: ${NEW_VERSION}" >&2
        echo "ERROR: new package version is not valid SemVer: ${NEW_VERSION}" >&2
        exit 1
    fi
    if [[ "${OLD_VERSION}" == "unknown" ]]
    then
        echo "AVISO: versão instalada desconhecida; comparação ignorada."
        echo "WARNING: installed version is unknown; comparison skipped."
        return
    fi
    if ! is_semver "${OLD_VERSION}"
    then
        echo "ERRO: versão instalada não segue SemVer: ${OLD_VERSION}" >&2
        echo "ERROR: installed version is not valid SemVer: ${OLD_VERSION}" >&2
        exit 1
    fi

    COMPARISON=$(semver_compare "${NEW_VERSION}" "${OLD_VERSION}")
    if [[ "${COMPARISON}" -eq 0 && "${ALLOW_SAME_VERSION}" -ne 1 ]]
    then
        echo "Atualização bloqueada: a versão ${NEW_VERSION} já está instalada." >&2
        echo "Update blocked: version ${NEW_VERSION} is already installed." >&2
        echo "Use --allow-same-version somente para uma reinstalação intencional." >&2
        exit 1
    fi
    if [[ "${COMPARISON}" -lt 0 && "${ALLOW_DOWNGRADE}" -ne 1 ]]
    then
        echo "Downgrade bloqueado: ${OLD_VERSION} -> ${NEW_VERSION}." >&2
        echo "Downgrade blocked: ${OLD_VERSION} -> ${NEW_VERSION}." >&2
        echo "Use --allow-downgrade somente quando a reversão for intencional." >&2
        exit 1
    fi
}

# =============================================================
# Confirma atualização | Confirm update
# =============================================================
confirm_update() {
    if [[ "${AUTO_YES}" -eq 1 ]]
    then
        return
    fi
    echo
    read -rp "Continuar atualização? (s/N) | Continue update? (y/N): " ANSWER
    if [[ "${ANSWER}" != "s" && "${ANSWER}" != "S" && "${ANSWER}" != "y" && "${ANSWER}" != "Y" ]]
    then
        echo
        echo "Atualização cancelada."
        echo "Update cancelled."
        exit 0
    fi
}

# =============================================================
# Criar backup | Create backup
# =============================================================
format_bytes() {
    local BYTES="$1"
    if command -v numfmt >/dev/null 2>&1
    then
        numfmt --to=iec-i --suffix=B "${BYTES}"
    else
        printf '%s bytes' "${BYTES}"
    fi
}

wait_with_progress() {
    local PROCESS_PID="$1"
    local MESSAGE="$2"
    local PROGRESS_FILE="${3:-}"
    local STARTED_AT
    local NOW
    local ELAPSED
    local WRITTEN
    local SPINNER='|/-\'
    local INDEX=0
    local FRAME

    STARTED_AT=$(date +%s)
    while kill -0 "${PROCESS_PID}" 2>/dev/null
    do
        NOW=$(date +%s)
        ELAPSED=$((NOW - STARTED_AT))
        WRITTEN=""
        if [[ -n "${PROGRESS_FILE}" ]] && [[ -f "${PROGRESS_FILE}" ]]
        then
            WRITTEN=$(stat -c '%s' "${PROGRESS_FILE}" 2>/dev/null || printf '0')
            WRITTEN=" - $(format_bytes "${WRITTEN}") gravados | written"
        fi
        FRAME="${SPINNER:$((INDEX % ${#SPINNER})):1}"
        INDEX=$((INDEX + 1))
        printf '\r[%s] %s - %02d:%02d:%02d%s' \
            "${FRAME}" \
            "${MESSAGE}" \
            "$((ELAPSED / 3600))" \
            "$(((ELAPSED % 3600) / 60))" \
            "$((ELAPSED % 60))" \
            "${WRITTEN}"
        sleep 1
    done

    if ! wait "${PROCESS_PID}"
    then
        printf '\n'
        return 1
    fi
    printf '\r[OK] %s%40s\n' "${MESSAGE}" ''
}

cleanup_partial_backup() {
    if [[ -n "${BACKUP_PROCESS_PID}" ]] && kill -0 "${BACKUP_PROCESS_PID}" 2>/dev/null
    then
        kill "${BACKUP_PROCESS_PID}" 2>/dev/null || true
        wait "${BACKUP_PROCESS_PID}" 2>/dev/null || true
    fi
    BACKUP_PROCESS_PID=""

    if [[ -n "${BACKUP_PART}" ]] && [[ -e "${BACKUP_PART}" ]]
    then
        rm -f -- "${BACKUP_PART}" || true
    fi
}

create_backup() {
    local INSTALL_PARENT
    local INSTALL_NAME
    local INSTALL_BYTES

    echo
    echo "Criando backup da instalação atual..."
    echo "Creating backup of current installation..."
    mkdir -p "${BACKUP_DIR}"
    BACKUP_FILE="${BACKUP_DIR}/dsm-before-update-$(date +%Y%m%d-%H%M%S).tar.gz"
    BACKUP_PART="${BACKUP_FILE}.part"
    INSTALL_PARENT=$(dirname "${INSTALL_DIR}")
    INSTALL_NAME=$(basename "${INSTALL_DIR}")
    INSTALL_BYTES=$(du -sb --exclude=game-data "${INSTALL_DIR}" | awk '{print $1}')

    rm -f -- "${BACKUP_PART}"
    echo "Tamanho de origem | Source size: $(format_bytes "${INSTALL_BYTES}")"

    if command -v pv >/dev/null 2>&1
    then
        echo "Progresso detalhado habilitado por pv | Detailed progress enabled by pv."
        tar -cf - --exclude="${INSTALL_NAME}/game-data" -C "${INSTALL_PARENT}" "${INSTALL_NAME}" \
            | pv --force --size "${INSTALL_BYTES}" --progress --timer --eta --rate --bytes \
            | gzip -c >"${BACKUP_PART}"
    else
        echo "pv não encontrado; exibindo progresso por tempo e bytes gravados."
        echo "pv not found; showing elapsed time and bytes written."
        tar -czf "${BACKUP_PART}" --exclude="${INSTALL_NAME}/game-data" -C "${INSTALL_PARENT}" "${INSTALL_NAME}" &
        BACKUP_PROCESS_PID=$!
        wait_with_progress "${BACKUP_PROCESS_PID}" "Compactando backup | Compressing backup" "${BACKUP_PART}"
        BACKUP_PROCESS_PID=""
    fi

    echo "Validando integridade do backup... | Validating backup integrity..."
    gzip -t "${BACKUP_PART}" &
    BACKUP_PROCESS_PID=$!
    wait_with_progress "${BACKUP_PROCESS_PID}" "Validando backup | Validating backup"
    BACKUP_PROCESS_PID=""

    mv -- "${BACKUP_PART}" "${BACKUP_FILE}"
    BACKUP_PART=""
    echo
    if [[ "${NO_BACKUP}" -eq 1 ]]
    then
        echo "Backup criado | Backup created:"
        echo "nenhum (--no-backup) | none (--no-backup)"
    else
        echo "Backup criado | Backup created:"
        echo "${BACKUP_FILE}"
    fi
}

create_database_backup() {
    [[ "${DSM_DATABASE_DRIVER:-sqlite}" != "sqlite" ]] || return 0
    local MANAGER="${NEW_SRC}/database/manager.py"
    local SUFFIX="sql"
    [[ "${DSM_DATABASE_DRIVER}" != "postgresql" ]] || SUFFIX="dump"
    DATABASE_BACKUP_FILE="${BACKUP_FILE%.tar.gz}.database.${SUFFIX}"
    [[ -f "${MANAGER}" ]] \
        || { echo "Gerenciador multi-database ausente: ${MANAGER}" >&2; return 1; }
    echo "Criando backup consistente do banco ${DSM_DATABASE_DRIVER}..."
    python3 "${MANAGER}" --root "${INSTALL_DIR}" \
        backup "${DATABASE_BACKUP_FILE}"
}

restore_database_backup() {
    [[ -n "${DATABASE_BACKUP_FILE}" \
        && -f "${DATABASE_BACKUP_FILE}" ]] || return 0
    local MANAGER="${INSTALL_DIR}/database/manager.py"
    [[ -f "${MANAGER}" ]] \
        || { echo "Gerenciador para restauração ausente: ${MANAGER}" >&2; return 1; }
    echo "Restaurando banco ${DSM_DATABASE_DRIVER} antes do rollback de arquivos..."
    python3 "${MANAGER}" --root "${INSTALL_DIR}" \
        restore "${DATABASE_BACKUP_FILE}" --confirm-restore
}

# =============================================================
# Process Guard
# =============================================================

run_process_guard()
{
    local GUARD

    GUARD="${NEW_SRC}/update-manager/process-guard.sh"

    if [[ ! -f "${GUARD}" ]]
    then
        echo
        echo "ERRO: Process Guard não encontrado."
        echo "ERROR: Process Guard not found."
        echo "${GUARD}"
        return 1
    fi

    # shellcheck source=/dev/null
    source "${GUARD}"

    if ! declare -F process_guard_pre_update >/dev/null
    then
        echo
        echo "ERRO: Process Guard inválido."
        echo "ERROR: Invalid Process Guard."
        echo "Função ausente: process_guard_pre_update"
        return 1
    fi

    echo
    echo "Verificando processos antes da atualização..."
    echo "Checking processes before update..."

    process_guard_pre_update
}


# =============================================================
# Parar serviços DSM | Stop DSM services
# =============================================================
capture_service_state() {
    local SERVICE_FILE
    local SERVICE_NAME
    local ACTIVE_STATE
    local SUB_STATE
    local UNIT_STATE
    local SERVICE_TYPE
    local RESTART_POLICY

    ACTIVE_SERVICES=()
    STOP_SERVICES=()
    RESTORE_SERVICES=()
    DISCOVERED_SERVICES=()
    SERVICE_ACTIVE_STATES=()
    SERVICE_SUB_STATES=()
    SERVICE_UNIT_STATES=()
    SERVICE_TYPES=()
    SERVICE_RESTART_POLICIES=()
    for SERVICE_FILE in "${SYSTEMD_DIR}"/dsm-*.service
    do
        [[ -e "${SERVICE_FILE}" ]] || continue
        SERVICE_NAME=$(basename "${SERVICE_FILE}")
        ACTIVE_STATE=$(systemctl show "${SERVICE_NAME}" --property=ActiveState --value 2>/dev/null) \
            || ACTIVE_STATE="${ACTIVE_STATE:-unknown}"
        SUB_STATE=$(systemctl show "${SERVICE_NAME}" --property=SubState --value 2>/dev/null) \
            || SUB_STATE="${SUB_STATE:-unknown}"
        SERVICE_TYPE=$(systemctl show "${SERVICE_NAME}" --property=Type --value 2>/dev/null) \
            || SERVICE_TYPE="${SERVICE_TYPE:-unknown}"
        RESTART_POLICY=$(systemctl show "${SERVICE_NAME}" --property=Restart --value 2>/dev/null) \
            || RESTART_POLICY="${RESTART_POLICY:-no}"
        UNIT_STATE=$(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null) \
            || UNIT_STATE="${UNIT_STATE:-unknown}"

        DISCOVERED_SERVICES+=("${SERVICE_NAME}")
        SERVICE_ACTIVE_STATES+=("${ACTIVE_STATE}")
        SERVICE_SUB_STATES+=("${SUB_STATE}")
        SERVICE_UNIT_STATES+=("${UNIT_STATE}")
        SERVICE_TYPES+=("${SERVICE_TYPE}")
        SERVICE_RESTART_POLICIES+=("${RESTART_POLICY}")

        case "${ACTIVE_STATE}" in
            active|activating)
                ACTIVE_SERVICES+=("${SERVICE_NAME}")
                STOP_SERVICES+=("${SERVICE_NAME}")
                ;;
        esac

        # Disabled services are never started by an update, even when they
        # happened to be running manually. Failed enabled units are retried.
        case "${UNIT_STATE}:${ACTIVE_STATE}" in
            enabled:active|enabled:activating|enabled:failed|enabled-runtime:active|enabled-runtime:activating|enabled-runtime:failed)
                RESTORE_SERVICES+=("${SERVICE_NAME}")
                ;;
        esac

        printf '  %s active=%s sub=%s enabled=%s type=%s restart=%s\n' \
            "${SERVICE_NAME}" "${ACTIVE_STATE}" "${SUB_STATE}" "${UNIT_STATE}" \
            "${SERVICE_TYPE}" "${RESTART_POLICY}"
    done

    echo
    echo "Serviços registrados | Services recorded: ${#DISCOVERED_SERVICES[@]}"
    echo "Serviços a restaurar | Services to restore: ${#RESTORE_SERVICES[@]}"
}

stop_services() {
    local SERVICE_NAME

    echo
    echo "Parando serviços DSM..."
    echo "Stopping DSM services..."
    for SERVICE_NAME in "${STOP_SERVICES[@]}"
    do
        echo "Parando | Stopping ${SERVICE_NAME}"
        systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    done
    echo
    echo "Serviços parados."
    echo "Services stopped."
}

# =============================================================
# Criar ambiente staging | Create staging environment
# =============================================================
create_staging() {
    echo
    echo "Criando ambiente temporário..."
    echo "Creating temporary environment..."
    rm -rf "${STAGING_DIR}"
    mkdir -p "${STAGING_DIR}"
    rsync -a "${NEW_SRC}/" "${STAGING_DIR}/"
    echo
    echo "Staging criado | Staging created."
}

# =============================================================
# Preservar somente dados duráveis | Preserve durable data only
# =============================================================
preserve_data() {
    echo
    echo "Preservando dados duráveis existentes..."
    echo "Preserving existing durable data..."

    # Explicit allowlist. Product code, caches, temporary workspaces and
    # retired top-level directories must always come from the new package.
    local -a PRESERVE_ITEMS=(
        "config"
        "data"
        "logs"
        "backups"
        "instances"
        "custom"
        "game-data"
    )
    local ITEM

    for ITEM in "${PRESERVE_ITEMS[@]}"
    do
        if [[ -d "${INSTALL_DIR}/${ITEM}" ]]
        then
            echo "Preservando | Preserving: ${ITEM}"
            mkdir -p "${STAGING_DIR}/${ITEM}"
            rsync -a "${INSTALL_DIR}/${ITEM}/" "${STAGING_DIR}/${ITEM}/"
        elif [[ -e "${INSTALL_DIR}/${ITEM}" || -L "${INSTALL_DIR}/${ITEM}" ]]
        then
            echo "Preservando | Preserving: ${ITEM}"
            cp -a "${INSTALL_DIR}/${ITEM}" "${STAGING_DIR}/${ITEM}"
        fi
    done

    # Runtime source code is replaced by the release. Preserve only its
    # explicitly scoped operational state while that state remains supported.
    if [[ -d "${INSTALL_DIR}/runtime/state" ]]
    then
        echo "Preservando | Preserving: runtime/state"
        mkdir -p "${STAGING_DIR}/runtime/state"
        rsync -a "${INSTALL_DIR}/runtime/state/" "${STAGING_DIR}/runtime/state/"
    fi

    echo
    echo "Dados duráveis preservados."
    echo "Durable data preserved."
}

# =============================================================
# Validar staging | Validate staging
# =============================================================
validate_staging() {
    echo
    echo "Validando nova instalação..."
    echo "Validating new installation..."
    REQUIRED=(
        "bin/dsm"
        "bin/cap"
        "core/bootstrap.sh"
    )
    for FILE in "${REQUIRED[@]}"
    do
        if [[ ! -f "${STAGING_DIR}/${FILE}" ]]
        then
            echo
            echo "Falha no staging | Staging failure."
            echo "Arquivo ausente | Missing file:"
            echo "${FILE}"
            exit 1
        fi
    done
    echo
    echo "Staging validado | Staging validated."
}

# =============================================================
# Aplicar atualização | Apply update
# =============================================================
apply_update() {
    echo
    echo "Aplicando nova versão DSM..."
    echo "Applying new DSM version..."
    if [[ ! -d "${STAGING_DIR}" ]]
    then
        echo "Staging inexistente | Staging does not exist."
        exit 1
    fi
    rm -rf "${INSTALL_DIR}"
    mv "${STAGING_DIR}" "${INSTALL_DIR}"
    echo
    echo "Arquivos atualizados."
    echo "Files updated."
}

update_version_file() {
    echo "${NEW_VERSION}" > "${INSTALL_DIR}/version"
}

update_configuration_version() {
    local KEY
    for KEY in DSM_VERSION INSTALLER_VERSION
    do
        if grep -q "^${KEY}=" "${CONFIG_FILE}"
        then
            sed -i "s|^${KEY}=.*|${KEY}=\"${NEW_VERSION}\"|" "${CONFIG_FILE}"
        else
            printf '%s="%s"\n' "${KEY}" "${NEW_VERSION}" >>"${CONFIG_FILE}"
        fi
    done

    if ! grep -q '^DSM_DATA_DIR=' "${CONFIG_FILE}"
    then
        printf 'DSM_DATA_DIR="%s/data"\n' "${INSTALL_DIR}" >>"${CONFIG_FILE}"
    fi
    if ! grep -q '^DSM_DATABASE=' "${CONFIG_FILE}"
    then
        printf 'DSM_DATABASE="%s/data/capivara.db"\n' "${INSTALL_DIR}" >>"${CONFIG_FILE}"
    fi
    if ! grep -q '^DSM_DATABASE_DRIVER=' "${CONFIG_FILE}"
    then
        printf 'DSM_DATABASE_DRIVER="sqlite"\n' >>"${CONFIG_FILE}"
    fi
}

migrate_database() {
    local MANAGER="${INSTALL_DIR}/database/manager.py"

    echo
    echo "Aplicando migrações do banco de dados..."
    echo "Applying database migrations..."
    if [[ ! -f "${MANAGER}" ]]
    then
        echo "Gerenciador de banco ausente | Database manager missing: ${MANAGER}"
        exit 1
    fi
    python3 "${MANAGER}" --root "${INSTALL_DIR}" migrate
}

# =============================================================
# Corrigir permissões | Fix permissions
# =============================================================
fix_permissions() {
    echo
    echo "Corrigindo permissões..."
    echo "Fixing permissions..."
    find "${INSTALL_DIR}" -type f -name "*.sh" -exec chmod +x {} \;
    chmod +x "${INSTALL_DIR}/bin/dsm"
    chmod +x "${INSTALL_DIR}/bin/cap"
    chown -R "${DSM_USER}:${DSM_GROUP}" "${INSTALL_DIR}"
    echo
    echo "Permissões ajustadas."
    echo "Permissions adjusted."
}

# =============================================================
# Criar links globais DSM/Capivara | Create global DSM/Capivara links
# =============================================================
install_command() {
    echo
    echo "Atualizando comandos globais..."
    echo "Updating global commands."

    ln -sf "${INSTALL_DIR}/bin/dsm" "${BIN_LINK}"
    ln -sf "${INSTALL_DIR}/bin/cap" "${CAP_LINK}"

    chmod +x "${BIN_LINK}"
    chmod +x "${CAP_LINK}"

    echo
    echo "Comandos DSM e Capivara atualizados."
    echo "DSM and Capivara commands updated."
}

# =============================================================
# Atualizar e reconciliar serviços Systemd | Update Systemd services
# =============================================================
update_systemd() {
    echo
    echo "Atualizando serviços Systemd..."
    echo "Updating Systemd services..."
    if [[ "${SYSTEMD_ENABLED}" -eq 0 ]]
    then
        echo "Systemd desativado | disabled."
        return
    fi

    local UNIT_TEMPLATE
    local UNIT_NAME
    local -a RETIRED_UNITS=(
        dsm-notification-engine.timer
        dsm-notification-center.timer
        dsm-backup-worker.service
        dsm-events-worker.service
        dsm-metrics-worker.service
        dsm-mods-worker.service
        dsm-server-worker.service
        dsm-event-queue-worker.service
        dsm-notification-center.service
        dsm-notification-engine.service
        dsm-discord-worker.service
        dsm-discord.service
        dsm-runtime-sync.service
    )

    for UNIT_NAME in "${RETIRED_UNITS[@]}"
    do
        systemctl disable --now "${UNIT_NAME}" >/dev/null 2>&1 || true
        rm -f -- "${SYSTEMD_DIR}/${UNIT_NAME}"
    done

    if [[ -d "${INSTALL_DIR}/systemd" ]]
    then
        for UNIT_TEMPLATE in \
            "${INSTALL_DIR}/systemd/"*.service \
            "${INSTALL_DIR}/systemd/"*.timer
        do
            [[ -e "${UNIT_TEMPLATE}" ]] || continue
            cp -f "${UNIT_TEMPLATE}" "${SYSTEMD_DIR}/"
        done

        for UNIT_TEMPLATE in \
            "${SYSTEMD_DIR}/"dsm-*.service \
            "${SYSTEMD_DIR}/"dsm-*.timer
        do
            [[ -e "${UNIT_TEMPLATE}" ]] || continue
            sed -i \
                -e "s|{{DSM_USER}}|${DSM_USER}|g" \
                -e "s|{{DSM_GROUP}}|${DSM_GROUP}|g" \
                "${UNIT_TEMPLATE}"
        done
    fi
    systemctl daemon-reload
    echo
    echo "Systemd reconciliado com a nova release."
    echo "Systemd reconciled with the new release."
}

# =============================================================
# Migrar workers legados do Dashboard | Migrate legacy Dashboard workers
# =============================================================
migrate_dashboard_worker_services() {
    local aggregate_unit="dsm-dashboard-worker.service"
    local service_name
    local active_service
    local aggregate_recorded=0
    local legacy_restore_required=0
    local legacy_worker_units=(
        dsm-backup-worker.service
        dsm-events-worker.service
        dsm-metrics-worker.service
        dsm-mods-worker.service
        dsm-server-worker.service
    )
    local migrated_active_services=()

    [[ "${SYSTEMD_ENABLED}" -eq 1 ]] || return 0
    [[ -f "${SYSTEMD_DIR}/${aggregate_unit}" ]] || return 0

    echo
    echo "Migrando workers legados do Dashboard..."
    echo "Migrating legacy Dashboard workers..."

    for service_name in "${legacy_worker_units[@]}"
    do
        if [[ -f "${SYSTEMD_DIR}/${service_name}" ]]
        then
            systemctl disable --now "${service_name}" 2>/dev/null || true
        fi
    done

    for active_service in "${RESTORE_SERVICES[@]}"
    do
        case " ${legacy_worker_units[*]} " in
            *" ${active_service} "*) legacy_restore_required=1; continue ;;
        esac
        migrated_active_services+=("${active_service}")
        [[ "${active_service}" == "${aggregate_unit}" ]] && aggregate_recorded=1
    done

    if [[ "${legacy_restore_required}" -eq 1 && "${aggregate_recorded}" -eq 0 ]]
    then
        migrated_active_services+=("${aggregate_unit}")
        systemctl enable "${aggregate_unit}"
    fi
    RESTORE_SERVICES=("${migrated_active_services[@]}")
    ACTIVE_SERVICES=("${RESTORE_SERVICES[@]}")

    echo "[OK] Workers consolidados em ${aggregate_unit}."
}

# =============================================================
# Reiniciar serviços DSM | Restart DSM services
# =============================================================
restart_services() {
    local SERVICE_NAME

    echo
    echo "Gerenciando serviços DSM..."
    echo "Managing DSM services..."
    if [[ "${SYSTEMD_ENABLED}" -eq 0 ]]
    then
        echo
        echo "Systemd desabilitado na configuração DSM."
        echo "Systemd disabled in DSM configuration."
        echo "Serviços não serão iniciados."
        echo "Services will not be started."
        return 0
    fi
    if [[ "${#RESTORE_SERVICES[@]}" -eq 0 ]]
    then
        echo
        echo "Nenhum serviço estava ativo antes da atualização."
        echo "No services were active before the update."
        return 0
    fi

    systemctl daemon-reload
    for SERVICE_NAME in "${RESTORE_SERVICES[@]}"
    do
        echo
        echo "Iniciando serviço | Starting service: ${SERVICE_NAME}"
        systemctl start "${SERVICE_NAME}" || {
            echo "[ERROR] Falha ao iniciar | Failed to start ${SERVICE_NAME}." >&2
            return 1
        }
        echo "[OK] ${SERVICE_NAME} iniciado | started."
    done
    echo
    echo "Processo de inicialização concluído."
    echo "Startup process completed."
}

service_ready() {
    local SERVICE_NAME="$1"
    local ACTIVE_STATE
    local SERVICE_TYPE
    local RESULT

    ACTIVE_STATE=$(systemctl show "${SERVICE_NAME}" --property=ActiveState --value 2>/dev/null || true)
    [[ "${ACTIVE_STATE}" == "active" ]] && return 0

    SERVICE_TYPE=$(systemctl show "${SERVICE_NAME}" --property=Type --value 2>/dev/null || true)
    RESULT=$(systemctl show "${SERVICE_NAME}" --property=Result --value 2>/dev/null || true)
    [[ "${SERVICE_TYPE}" == "oneshot" && "${ACTIVE_STATE}" == "inactive" && "${RESULT}" == "success" ]]
}

wait_for_service_readiness() {
    local SERVICE_NAME="$1"
    local DEADLINE=$((SECONDS + READINESS_TIMEOUT))

    until service_ready "${SERVICE_NAME}"
    do
        if (( SECONDS >= DEADLINE ))
        then
            echo "[ERROR] Timeout aguardando serviço | waiting for service: ${SERVICE_NAME}" >&2
            return 1
        fi
        sleep "${READINESS_INTERVAL}"
    done
    echo "[OK] Serviço pronto | Service ready: ${SERVICE_NAME}"
}

wait_for_dashboard_readiness() {
    local DASHBOARD_URL="$1"
    local DEADLINE=$((SECONDS + READINESS_TIMEOUT))

    until curl --fail --silent --show-error --max-time 5 "${DASHBOARD_URL}" >/dev/null
    do
        if (( SECONDS >= DEADLINE ))
        then
            echo "[ERROR] Timeout aguardando Dashboard | waiting for Dashboard: ${DASHBOARD_URL}" >&2
            return 1
        fi
        sleep "${READINESS_INTERVAL}"
    done
}

validate_runtime_readiness() {
    local SERVICE_NAME
    local DASHBOARD_RESTORED=0
    local DASHBOARD_PORT_VALUE="8080"

    echo
    echo "Validando readiness pós-atualização..."
    echo "Validating post-update readiness..."
    for SERVICE_NAME in "${RESTORE_SERVICES[@]}"
    do
        wait_for_service_readiness "${SERVICE_NAME}"
        [[ "${SERVICE_NAME}" == "dsm-dashboard.service" ]] && DASHBOARD_RESTORED=1
    done

    [[ -x "${INSTALL_DIR}/bin/cap" ]] || {
        echo "[ERROR] CLI cap não está executável | cap CLI is not executable." >&2
        return 1
    }
    "${INSTALL_DIR}/bin/cap" --help >/dev/null
    echo "[OK] CLI cap"

    python3 "${INSTALL_DIR}/database/manager.py" --root "${INSTALL_DIR}" check >/dev/null
    echo "[OK] Database (${DSM_DATABASE_DRIVER})"

    if [[ "${DASHBOARD_RESTORED}" -eq 1 ]]
    then
        if [[ -r "${INSTALL_DIR}/dashboard/config/dashboard.conf" ]]
        then
            DASHBOARD_PORT_VALUE=$(awk -F= '$1 == "PORT" {gsub(/[^0-9]/, "", $2); print $2; exit}' \
                "${INSTALL_DIR}/dashboard/config/dashboard.conf")
            DASHBOARD_PORT_VALUE="${DASHBOARD_PORT_VALUE:-8080}"
        fi
        wait_for_dashboard_readiness \
            "http://127.0.0.1:${DASHBOARD_PORT_VALUE}/health"
        echo "[OK] Dashboard HTTP /health"
    fi
}

# =============================================================
# Validar instalação final | Validate final installation
# =============================================================
validate_final_installation() {
    echo
    echo "Validando instalação final..."
    echo "Validating final installation..."
    REQUIRED_FILES=(
        "${INSTALL_DIR}/bin/dsm"
        "${INSTALL_DIR}/bin/cap"
        "${INSTALL_DIR}/core/bootstrap.sh"
        "${INSTALL_DIR}/config/dsm.conf"
    )
    for FILE in "${REQUIRED_FILES[@]}"
    do
        if [[ ! -f "${FILE}" ]]
        then
            echo
            echo "Arquivo ausente após atualização:"
            echo "File missing after update:"
            echo "${FILE}"
            exit 1
        fi
    done
    echo
    echo "Arquivos principais OK."
    echo "Main files OK."
}

# =============================================================
# Executar Doctor DSM | Run DSM Doctor
# =============================================================
run_doctor() {
    echo
    echo "Executando diagnóstico DSM..."
    echo "Running DSM diagnosis..."
    if [[ -x "${INSTALL_DIR}/bin/dsm" ]]
    then
        "${INSTALL_DIR}/bin/dsm" doctor || echo "Aviso | Warning: Doctor encontrou problemas | found issues."
    else
        echo
        echo "Comando DSM não encontrado | DSM command not found."
        exit 1
    fi
}

# =============================================================
# Check Internet
# =============================================================
check_internet() {
    if curl -fsSL https://github.com >/dev/null
    then
        echo "Internet OK."
    else
        echo "Aviso | Warning: Sem acesso ao GitHub | No access to GitHub."
        echo "Continuando usando pacote local | Continuing using local package."
    fi
}

# =============================================================
# Verificar serviços | Check services
# =============================================================
check_services() {
    local SERVICE_NAME

    echo
    echo "Verificando serviços DSM..."
    echo "Checking DSM services..."
    for SERVICE_NAME in "${RESTORE_SERVICES[@]}"
    do
        if systemctl is-active --quiet "${SERVICE_NAME}"
        then
            echo
            echo "[OK] ${SERVICE_NAME}"
        else
            echo
            echo "[WARN] ${SERVICE_NAME} parado | stopped"
        fi
    done
}

# =============================================================
# Limpeza temporária | Temporary cleanup
# =============================================================
cleanup_update() {
    echo
    echo "Removendo arquivos temporários..."
    echo "Removing temporary files..."
    rm -rf "${STAGING_DIR}"
    echo
    echo "Limpeza concluída | Cleanup completed."
}

# =============================================================
# Verificar execução como root | Check root execution
# =============================================================
require_root() {
    if [[ "${EUID}" -ne 0 ]]
    then
        echo
        echo "======================================"
        echo " ERRO: Permissão insuficiente"
        echo " ERROR: Insufficient permission"
        echo "======================================"
        echo
        echo "Este script precisa ser executado como root."
        echo "This script must be run as root."
        echo
        echo "Execute:"
        echo "sudo ./update.sh <pacote-dsm>"
        echo
        exit 1
    fi
    echo
    echo "Permissão root confirmada."
    echo "Root permission confirmed."
}

# =============================================================
# Verificar espaço disponível em disco | Check available disk space
# =============================================================
check_disk() {
    echo
    echo "Verificando espaço em disco..."
    echo "Checking disk space..."
    # Espaço livre em MB na partição raiz | Free space in MB on root partition
    INSTALL_BYTES=$(du -sb "${INSTALL_DIR}" | awk '{print $1}')
    # Mínimo necessário: 2 GB livres | Minimum required: 2 GB free
    FREE_BYTES=$(df --output=avail -B1 "${INSTALL_DIR}" | tail -1 | tr -d ' ')
    REQUIRED_BYTES=$((INSTALL_BYTES * 2))
    if (( FREE_BYTES < REQUIRED_BYTES ))
    then
        echo
        echo "======================================"
        echo " ERRO: Espaço insuficiente"
        echo " ERROR: Insufficient space"
        echo "======================================"
        echo
        echo "Espaço disponível | Available bytes: ${FREE_BYTES}"
        echo "Necessário mínimo | Required bytes: ${REQUIRED_BYTES}"
        echo
        echo "Libere espaço antes de continuar."
        echo "Free up space before continuing."
        exit 1
    fi
    echo
    echo "Espaço disponível | Available bytes: ${FREE_BYTES}"
    echo "Necessário estimado | Estimated required bytes: ${REQUIRED_BYTES}"
    echo "Espaço em disco OK | Disk space OK."
}

# =============================================================
# Validar argumentos de entrada | Validate input arguments
# =============================================================
validate_argument() {
    echo
    echo "Validando argumentos..."
    echo "Validating arguments..."
    if [[ -z "${NEW_SRC}" ]]
    then
        echo
        echo "======================================"
        echo " ERRO: Pacote DSM não informado"
        echo " ERROR: DSM package not specified"
        echo "======================================"
        echo
        echo "Uso correto | Correct usage:"
        echo "sudo ./update.sh /caminho/DSM-nova-versao"
        echo
        exit 1
    fi
    if [[ ! -d "${NEW_SRC}" ]]
    then
        echo
        echo "======================================"
        echo " ERRO: Pacote DSM inexistente"
        echo " ERROR: DSM package does not exist"
        echo "======================================"
        echo
        echo "Diretório informado | Directory specified:"
        echo "${NEW_SRC}"
        echo
        exit 1
    fi
    # Normaliza caminho absoluto | Normalize absolute path
    NEW_SRC="$(realpath "${NEW_SRC}")"
    echo
    echo "Pacote DSM encontrado | DSM package found:"
    echo "${NEW_SRC}"
    echo
    echo "Argumentos válidos | Valid arguments."
}

# =============================================================
# Relatório final | Final report
# =============================================================
update_summary() {
    echo
    echo "======================================"
    echo " Atualização DSM concluída"
    echo " DSM Update completed"
    echo "======================================"
    echo
    echo "Versão anterior | Previous version:"
    echo "${OLD_VERSION}"
    echo
    echo "Nova versão | New version:"
    echo "${NEW_VERSION}"
    echo
    if [[ "${NO_BACKUP}" -eq 1 ]]
    then
        echo "Backup utilizado | Backup used:"
        echo "nenhum (--no-backup) | none (--no-backup)"
    else
        echo "Backup utilizado | Backup used:"
        echo "${BACKUP_FILE}"
    fi
    echo
    echo "Log:"
    echo "${LOG_DIR}/update.log"
    echo
    echo "DSM atualizado com sucesso."
    echo "DSM updated successfully."
}

# =============================================================
# Fluxo principal de atualização | Main update flow
# =============================================================
main() {
    echo
    echo "Iniciando atualização DSM..."
    echo "Starting DSM update..."
    parse_arguments "$@"
    # Ambiente | Environment
    require_root
    # O pacote instalado pode ser substituído durante esta execução. Nunca
    # mantenha o shell ou jobs de progresso dentro de /opt/dsm.
    cd "$(dirname "${INSTALL_DIR}")" || {
        echo "Não foi possível acessar o diretório pai da instalação: ${INSTALL_DIR}" >&2
        return 1
    }
    initialize_logging
    # Validar instalação | Validate installation
    load_configuration
    validate_runtime_account
    validate_argument
    validate_package
    check_internet
    check_disk
    # Versões | Versions
    read_versions
    enforce_version_policy
    confirm_update
    # Segurança | Security
    if [[ "${NO_BACKUP}" -eq 1 ]]
    then
        echo
        echo "AVISO: backup pré-atualização desativado por --no-backup."
        echo "WARNING: pre-update backup disabled by --no-backup."
        echo "Rollback automático não estará disponível se a atualização falhar."
        echo "Automatic rollback will not be available if the update fails."
    else
        create_backup
        create_database_backup
    fi
    # Preparação | Preparation
    run_process_guard
    capture_service_state
    UPDATE_TRANSACTION_STARTED=1
    stop_services
    create_staging
    preserve_data
    validate_staging
    # Atualização | Update
    apply_update
    update_version_file
    update_configuration_version
    migrate_database
    fix_permissions
    install_command
    update_systemd
    migrate_dashboard_worker_services
    # Inicialização | Startup
    restart_services
    # Validação | Validation
    validate_final_installation
    validate_runtime_readiness
    run_doctor
    check_services
    # Finalização | Finalization
    cleanup_update
    update_summary
}

# =============================================================
# Tratamento de falha da atualização | Update failure handling
# =============================================================
update_failed() {
    local ERROR_LINE="$1"
    trap - ERR
    echo
    echo "======================================"
    echo " FALHA DURANTE A ATUALIZAÇÃO"
    echo " FAILURE DURING UPDATE"
    echo "======================================"
    echo
    echo "Linha do erro | Error line: ${ERROR_LINE}"
    collect_failure_diagnostics "${ERROR_LINE}"
    echo
    cleanup_partial_backup
    # Só executa rollback se existir backup | Only run rollback if backup exists
    if [[ -n "${BACKUP_FILE}" ]] && [[ -f "${BACKUP_FILE}" ]]
    then
        rollback
    else
        echo
        echo "Rollback não executado."
        echo "Rollback not executed."
        echo "Nenhum backup válido disponível."
        echo "No valid backup available."
    fi
    echo
    echo "Processo interrompido."
    echo "Process interrupted."
    exit 1
}

collect_failure_diagnostics() {
    local ERROR_LINE="$1"
    # Keep diagnostics outside INSTALL_DIR because rollback replaces that
    # directory from the pre-update archive.
    local DIAGNOSTIC_DIR="${BACKUP_DIR}/update-diagnostics-$(date '+%Y%m%d-%H%M%S')-$$"
    local SERVICE_NAME

    mkdir -p "${DIAGNOSTIC_DIR}" 2>/dev/null || return 0
    {
        printf 'error_line=%s\n' "${ERROR_LINE}"
        printf 'old_version=%s\nnew_version=%s\n' "${OLD_VERSION}" "${NEW_VERSION}"
        printf 'restore_services=%s\n' "${RESTORE_SERVICES[*]}"
    } >"${DIAGNOSTIC_DIR}/transaction.txt" 2>/dev/null || true
    for SERVICE_NAME in "${DISCOVERED_SERVICES[@]}"
    do
        systemctl status --no-pager --full "${SERVICE_NAME}" \
            >"${DIAGNOSTIC_DIR}/${SERVICE_NAME}.status.txt" 2>&1 || true
        journalctl -u "${SERVICE_NAME}" --no-pager -n 100 \
            >"${DIAGNOSTIC_DIR}/${SERVICE_NAME}.journal.txt" 2>&1 || true
    done
    echo "Diagnóstico preservado | Diagnostics saved: ${DIAGNOSTIC_DIR}"
}

update_interrupted() {
    trap - INT TERM
    echo
    echo "Atualização interrompida | Update interrupted."
    if [[ "${UPDATE_TRANSACTION_STARTED}" -eq 1 ]]
    then
        update_failed "signal"
    fi
    exit 130
}

# =============================================================
# Rollback seguro | Safe rollback
# =============================================================
rollback() {
    local GAME_DATA_ROLLBACK="${INSTALL_DIR}.game-data-rollback"

    echo
    echo "======================================"
    echo " Executando rollback"
    echo " Executing rollback"
    echo "======================================"
    echo
    if [[ ! -f "${BACKUP_FILE}" ]]
    then
        echo "Backup não encontrado | not found."
        return 1
    fi
    restore_database_backup
    echo "Removendo instalação quebrada..."
    echo "Removing broken installation..."
    rm -rf "${GAME_DATA_ROLLBACK}"
    if [[ -d "${INSTALL_DIR}/game-data" ]]
    then
        mv "${INSTALL_DIR}/game-data" "${GAME_DATA_ROLLBACK}"
    fi
    rm -rf "${INSTALL_DIR}"
    echo "Restaurando backup..."
    echo "Restoring backup..."
    tar -xzf "${BACKUP_FILE}" -C /opt
    if [[ -d "${GAME_DATA_ROLLBACK}" ]]
    then
        mv "${GAME_DATA_ROLLBACK}" "${INSTALL_DIR}/game-data"
    fi
    echo
    echo "Backup restaurado | restored."
    # Restaurar permissões | Restore permissions
    if [[ -n "${DSM_USER}" ]] && [[ -n "${DSM_GROUP}" ]]
    then
        echo
        echo "Restaurando permissões..."
        echo "Restoring permissions..."
        chown -R "${DSM_USER}:${DSM_GROUP}" "${INSTALL_DIR}" 2>/dev/null || true
    fi
    # Restore the unit files shipped by the previous installation before
    # reloading systemd; otherwise rollback can run old code with new units.
    if [[ -d "${INSTALL_DIR}/systemd" ]]
    then
        local UNIT_TEMPLATE
        for UNIT_TEMPLATE in \
            "${INSTALL_DIR}/systemd/"*.service \
            "${INSTALL_DIR}/systemd/"*.timer
        do
            [[ -e "${UNIT_TEMPLATE}" ]] || continue
            cp -f "${UNIT_TEMPLATE}" "${SYSTEMD_DIR}/"
        done
    fi
    # Atualizar Systemd | Update Systemd
    echo
    echo "Recarregando Systemd..."
    echo "Reloading Systemd..."
    systemctl daemon-reload 2>/dev/null || true
    restart_services 2>/dev/null || true
    # Remover staging incompleto | Remove incomplete staging
    rm -rf "${STAGING_DIR}"
    echo
    echo "Rollback concluído | completed."
}

trap 'update_failed $LINENO' ERR

# =============================================================
# Limpeza | Cleanup
# =============================================================
cleanup() {
    echo
    echo "Realizando limpeza..."
    echo "Performing cleanup..."
    rm -rf "${STAGING_DIR}"
    if [[ -n "${BACKUP_PART}" ]]
    then
        cleanup_partial_backup
    fi
}

# =============================================================
# Finalização | Finalization
# =============================================================
finish_update() {
    echo
    echo "======================================"
    echo " Atualização concluída com sucesso"
    echo " Update completed successfully"
    echo "======================================"
    echo
    echo "Versão anterior | Previous version:"
    echo "${OLD_VERSION}"
    echo
    echo "Nova versão | New version:"
    echo "${NEW_VERSION}"
    echo
    if [[ "${NO_BACKUP}" -eq 1 ]]
    then
        echo "Backup criado | Backup created:"
        echo "nenhum (--no-backup) | none (--no-backup)"
    else
        echo "Backup criado | Backup created:"
        echo "${BACKUP_FILE}"
    fi
    echo
    echo "Log:"
    echo "${LOG_DIR}/update.log"
}

# =============================================================
# Start
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    trap cleanup_partial_backup EXIT
    trap update_interrupted INT TERM
    main "$@"
fi
