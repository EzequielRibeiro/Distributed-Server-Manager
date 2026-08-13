#!/bin/bash
# =============================================================
# core/bootstrap.sh - MÓDULO 01 (CORE)
#
# Inicialização do DSM
# DSM Initialization
#
# Responsável por:
# Responsible for:
#   - definir ambiente DSM | defining DSM environment
#   - carregar configuração principal | loading main configuration
#   - carregar funções comuns | loading common functions
#   - preparar módulos | preparing modules
#
# Fonte única: | Single source:
#
#   /opt/dsm/config/dsm.conf
#
# =============================================================

# =============================================================
# Requisitos de Sistema | System Requirements
# =============================================================
if [ "${BASH_VERSINFO:-0}" -lt 4 ]; then
    echo "ERRO: O DSM requer Bash 4.0 ou superior."
    echo "ERROR: DSM requires Bash 4.0 or higher."
    return 1 2>/dev/null || exit 1
fi

# =============================================================
# Evita carregar o bootstrap mais de uma vez
# Prevent loading bootstrap more than once
# =============================================================
if [[ "${DSM_BOOTSTRAP_RUNNING:-0}" == "1" ]]
then
    return 0 2>/dev/null || exit 0
fi

if [[ -n "${DSM_BOOTSTRAP_LOADED:-}" ]]
then
    # Recarregar bibliotecas essenciais
    # Reload essential libraries
    if [[ -f "${DSM_ROOT}/core/logger.sh" ]]
    then
        source "${DSM_ROOT}/core/logger.sh"
    fi

    return 0 2>/dev/null || exit 0
fi

export DSM_BOOTSTRAP_RUNNING=1

# =============================================================
# Definir raiz DSM
# Define DSM root
# =============================================================
if [[ -z "${DSM_ROOT:-}" ]]; then
    export DSM_ROOT="/opt/dsm"
fi

# =============================================================
# Diretórios principais
# Main directories
# =============================================================
export DSM_CONFIG_DIR="${DSM_ROOT}/config"
export DSM_MODULE_DIR="${DSM_ROOT}"

export DSM_CONFIG_FILE="${DSM_CONFIG_DIR}/dsm.conf"
export DSM_CONFIG="${DSM_CONFIG_FILE}"

# =============================================================
# Validar instalação
# Validate installation
# =============================================================
if [[ ! -d "${DSM_ROOT}" ]]; then
    echo "DSM não encontrado:"
    echo "DSM not found:"
    echo "${DSM_ROOT}"
    return 1 2>/dev/null || exit 1
fi

if [[ ! -f "${DSM_CONFIG_FILE}" ]]; then
    echo "Arquivo de configuração não encontrado:"
    echo "Configuration file not found:"
    echo "${DSM_CONFIG_FILE}"
    return 1 2>/dev/null || exit 1
fi

# =============================================================
# Logger
# =============================================================
if [[ -f "${DSM_ROOT}/core/logger.sh" ]]; then
    # shellcheck source=/dev/null
    source "${DSM_ROOT}/core/logger.sh"
fi

# =============================================================
# Configuração
# Configuration
# =============================================================
# shellcheck source=/dev/null
source "${DSM_CONFIG_FILE}" || {
    if declare -F log_error >/dev/null; then
        log_error "Falha ao carregar ${DSM_CONFIG_FILE}"
        log_error "Failed to load ${DSM_CONFIG_FILE}"
    else
        echo "Falha ao carregar ${DSM_CONFIG_FILE}"
        echo "Failed to load ${DSM_CONFIG_FILE}"
    fi

    return 1 2>/dev/null || exit 1
}

# =============================================================
# Validar variáveis mínimas
# Validate minimum variables
# =============================================================
BOOT_REQUIRED=(
    DSM_USER
    DSM_HOME
    INSTANCE_NAME
    LINUXGSM_PATH
    SERVERFILES_PATH
)

BOOT_FAILED=0

for var in "${BOOT_REQUIRED[@]}"
do
    case "$var" in
        DSM_USER)
            VALUE="${DSM_USER:-}"
        ;;
        DSM_HOME)
            VALUE="${DSM_HOME:-}"
        ;;
        INSTANCE_NAME)
            VALUE="${INSTANCE_NAME:-}"
        ;;
        LINUXGSM_PATH)
            VALUE="${LINUXGSM_PATH:-}"
        ;;
        SERVERFILES_PATH)
            VALUE="${SERVERFILES_PATH:-}"
        ;;
    esac

    if [[ -z "$VALUE" ]]
    then
        log_error "Variável obrigatória não definida:"
        log_error "Required variable not defined:"
        echo "$var"
        BOOT_FAILED=1
    fi
done

if [[ "$BOOT_FAILED" -eq 1 ]]
then
    return 1 2>/dev/null || exit 1
fi

# =============================================================
# Exportar ambiente
# Export environment
# =============================================================
export DSM_ROOT
export DSM_CONFIG_DIR
export DSM_CONFIG_FILE

export DSM_USER
export DSM_HOME
export DSM_GROUP

export INSTANCE_NAME
export LINUXGSM_PATH
export SERVERFILES_PATH

export APPID_SERVER
export APPID_WORKSHOP

# =============================================================
# Compatibilidade
# Compatibility
# =============================================================
unset LGSM_DIR 2>/dev/null || true
unset LGSM_USER 2>/dev/null || true
unset LGSM_HOME 2>/dev/null || true

# =============================================================
# Biblioteca de configuração
# Configuration library
# =============================================================
if [[ -f "${DSM_ROOT}/core/config.sh" ]]; then
    # shellcheck source=/dev/null
    source "${DSM_ROOT}/core/config.sh"
fi

# =============================================================
# Biblioteca de servidor
# Server library
# =============================================================
if [[ -f "${DSM_ROOT}/core/server.sh" ]]; then
    # shellcheck source=/dev/null
    source "${DSM_ROOT}/core/server.sh"
fi

# =============================================================
# Ambiente DSM
# DSM Environment
# =============================================================
dsm_environment() {
    echo
    echo "DSM Environment"
    echo "-----------------------------"

    printf "%-18s %s\n" "Root:"        "${DSM_ROOT}"
    printf "%-18s %s\n" "Usuário:"     "${DSM_USER}"
    printf "%-18s %s\n" "User:"        "${DSM_USER}"
    printf "%-18s %s\n" "Home:"        "${DSM_HOME}"
    printf "%-18s %s\n" "LinuxGSM:"    "${LINUXGSM_PATH}"
    printf "%-18s %s\n" "Serverfiles:" "${SERVERFILES_PATH}"
    printf "%-18s %s\n" "Instância:"   "${INSTANCE_NAME}"
    printf "%-18s %s\n" "Instance:"    "${INSTANCE_NAME}"

    echo
}

# =============================================================
# Helpers de exibição
# Display helpers
# =============================================================
print_title()
{
    echo
    echo "============================================================"
    echo " $1"
    echo "============================================================"
}

print_separator()
{
    echo "------------------------------------------------------------"
}

print_ok()
{
    printf "[OK] %s\n" "$*"
}

print_warn()
{
    printf "[WARN] %s\n" "$*"
}

print_fail()
{
    printf "[FAIL] %s\n" "$*"
}

print_info()
{
    printf "[INFO] %s\n" "$*"
}

# =============================================================
# Normalização da configuração DSM
# DSM configuration normalization
#
# Garante que variáveis obrigatórias existam tanto em memória
# quanto no dsm.conf.
# Ensures that mandatory variables exist both in memory
# and in dsm.conf.
# =============================================================
dsm_config_defaults()
{
    #
    # APPID DayZ Workshop
    #
    if [ -z "${APPID_WORKSHOP:-}" ]
    then
        APPID_WORKSHOP="221100"
        export APPID_WORKSHOP

        if ! grep -q '^APPID_WORKSHOP=' "${DSM_CONFIG_FILE}" 2>/dev/null
        then
            echo 'APPID_WORKSHOP="221100"' >> "${DSM_CONFIG_FILE}"

            log_info \
            "APPID_WORKSHOP adicionado automaticamente ao dsm.conf."
            log_info \
            "APPID_WORKSHOP automatically added to dsm.conf."
        fi
    fi

    #
    # APPID DayZ Dedicated Server
    #
    if [ -z "${APPID_SERVER:-}" ]
    then
        APPID_SERVER="223350"
        export APPID_SERVER

        if ! grep -q '^APPID_SERVER=' "${DSM_CONFIG}" 2>/dev/null
        then
            echo 'APPID_SERVER="223350"' >> "${DSM_CONFIG}"

            log_info \
            "APPID_SERVER adicionado automaticamente ao dsm.conf."
            log_info \
            "APPID_SERVER automatically added to dsm.conf."
        fi
    fi
}

dsm_config_defaults

# =============================================================
# Execução direta
# Direct execution
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    dsm_environment
fi
