#!/usr/bin/env bash
# =============================================================
# core/config.sh - configuração compartilhada do Capivara DSM
# Fonte única: /opt/dsm/config/dsm.conf
# =============================================================

LOG_MODULE="core"

if [ -z "${DSM_ROOT:-}" ]
then
    echo "DSM_ROOT não definido." >&2
    echo "DSM_ROOT not defined." >&2
    return 1 2>/dev/null || exit 1
fi

readonly DSM_CONFIG_FILE="${DSM_ROOT}/config/dsm.conf"

# Somente identidade/configuração global é obrigatória aqui. Dados específicos
# de jogo e processo pertencem ao Catalog/RuntimeDefinition da instância.
CONFIG_REQUIRED_VARS=(
    DSM_USER
    DSM_GROUP
    DSM_HOME
    DSM_DATABASE_DRIVER
)

config_load()
{
    if [ ! -r "${DSM_CONFIG_FILE}" ]
    then
        log_error "Arquivo de configuração não encontrado:"
        log_error "Configuration file not found:"
        echo "${DSM_CONFIG_FILE}"
        return 1
    fi

    # shellcheck source=/dev/null
    source "${DSM_CONFIG_FILE}" || {
        log_error "Falha ao carregar configuração."
        log_error "Failed to load configuration."
        return 1
    }
    return 0
}

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
        log_error "Configuração incompleta."
        log_error "Incomplete configuration."
        echo
        echo "Variáveis ausentes:"
        echo "Missing variables:"
        printf " - %s\n" "${missing[@]}"
        return 1
    fi
    return 0
}

config_get()
{
    local key="$1"
    grep -E "^${key}=" "${DSM_CONFIG_FILE}" 2>/dev/null |
        tail -n1 |
        cut -d'=' -f2- |
        sed 's/^"//;s/"$//'
}

config_set()
{
    local key="$1"
    local value="$2"
    local escaped

    escaped=$(printf '%s' "${value}" | sed 's/[\/&]/\\&/g')

    if grep -q "^${key}=" "${DSM_CONFIG_FILE}" 2>/dev/null
    then
        sed -i "s#^${key}=.*#${key}=\"${escaped}\"#" "${DSM_CONFIG_FILE}"
    else
        printf '%s="%s"\n' "${key}" "${value}" >> "${DSM_CONFIG_FILE}"
    fi

    config_load >/dev/null 2>&1
}

config_show()
{
    if [ ! -f "${DSM_CONFIG_FILE}" ]
    then
        log_error "Configuração não encontrada."
        log_error "Configuration not found."
        return 1
    fi

    section "Configuração DSM"
    grep -Ev '^[[:space:]]*(#|$)' "${DSM_CONFIG_FILE}"
}

config_load

if [ "${BASH_SOURCE[0]}" = "$0" ]
then
    config_validate || exit 1
    config_show
fi
