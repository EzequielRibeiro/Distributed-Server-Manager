#!/bin/bash
# =============================================================
# core/config.sh - MÓDULO 01 (CORE)
#
# Responsável por:
# Responsible for:
#
# - carregar configuração DSM | loading DSM configuration
# - validar variáveis obrigatórias | validating mandatory variables
# - fornecer acesso às configurações | providing access to configurations
#
# Fonte única: | Single source:
#
#   /opt/dsm/config/dsm.conf
#
# Removido: | Removed:
#
#   settings.conf
#   LGSM_DIR
#
# =============================================================

LOG_MODULE="core"

# =============================================================
# Validar ambiente
# Validate environment
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    echo "DSM_ROOT não definido." >&2
    echo "DSM_ROOT not defined." >&2
    return 1 2>/dev/null || exit 1
fi

readonly DSM_CONFIG_FILE="${DSM_ROOT}/config/dsm.conf"

# =============================================================
# Variáveis obrigatórias
# Mandatory variables
# =============================================================
CONFIG_REQUIRED_VARS=(
    DSM_USER
    DSM_GROUP
    DSM_HOME
    INSTANCE_NAME
    LINUXGSM_PATH
    SERVERFILES_PATH
    STEAMCMD_DIR
    APPID_SERVER
    BACKUP_DIR
    SERVER_PORT
)

# =============================================================
# Carregar configuração
# Load configuration
# =============================================================
config_load()
{
    if [ ! -r "${DSM_CONFIG_FILE}" ]
    then
        log_error \
        "Arquivo de configuração não encontrado:"
        log_error \
        "Configuration file not found:"
        echo "${DSM_CONFIG_FILE}"
        return 1
    fi

    # shellcheck source=/dev/null
    source "${DSM_CONFIG_FILE}" || {
        log_error \
        "Falha ao carregar configuração."
        log_error \
        "Failed to load configuration."
        return 1
    }

    return 0
}

# =============================================================
# Validar configuração
# Validate configuration
# =============================================================
config_validate()
{
    local missing=()
    local var

    for var in "${CONFIG_REQUIRED_VARS[@]}"
    do
        if [ -z "${!var:-}" ]
        then
            missing+=("${var}")
        fi
    done

    if [ "${#missing[@]}" -gt 0 ]
    then
        log_error \
        "Configuração incompleta."
        log_error \
        "Incomplete configuration."
        echo
        echo "Variáveis ausentes:"
        echo "Missing variables:"
        printf " - %s\n" "${missing[@]}"

        return 1
    fi

    return 0
}

# =============================================================
# Obter valor
# Get value
#
# Uso: | Usage:
#
# config_get SERVERFILES_PATH
#
# =============================================================
config_get()
{
    local key="$1"

    grep -E "^${key}=" \
        "${DSM_CONFIG_FILE}" \
        2>/dev/null |
        tail -n1 |
        cut -d'=' -f2- |
        sed 's/^"//;s/"$//'
}

# =============================================================
# Alterar configuração
# Change configuration
#
# Uso: | Usage:
#
# config_set SERVER_PORT 2302
#
# =============================================================
config_set()
{
    local key="$1"
    local value="$2"
    local escaped

    escaped=$(printf '%s' "${value}" | sed 's/[\/&]/\\&/g')

    if grep -q "^${key}=" "${DSM_CONFIG_FILE}" 2>/dev/null
    then
        sed -i \
        "s#^${key}=.*#${key}=\"${escaped}\"#" \
        "${DSM_CONFIG_FILE}"

    else
        printf '%s="%s"\n' \
        "${key}" \
        "${value}" \
        >> "${DSM_CONFIG_FILE}"
    fi

    config_load >/dev/null 2>&1
}

# =============================================================
# Mostrar configuração
# Show configuration
#
# Uso: | Usage:
#
# dsm config show
#
# =============================================================
config_show()
{
    if [ ! -f "${DSM_CONFIG_FILE}" ]
    then
        log_error \
        "Configuração não encontrada."
        log_error \
        "Configuration not found."
        return 1
    fi

    section \
    "Configuração DSM"
    section \
    "DSM Configuration"

    grep -Ev \
    '^[[:space:]]*(#|$)' \
    "${DSM_CONFIG_FILE}"
}

# =============================================================
# Carregamento automático
# Automatic loading
#
# Todos os módulos que fazem: | All modules that do:
#
# source core/config.sh
#
# já recebem as variáveis carregadas. | already receive the loaded variables.
#
# =============================================================
config_load

# =============================================================
# Execução direta
# Direct execution
# =============================================================
if [ "${BASH_SOURCE[0]}" = "$0" ]
then
    config_validate || exit 1
    config_show
fi
