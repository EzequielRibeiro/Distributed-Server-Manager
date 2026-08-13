#!/bin/bash
# =============================================================
# mods/import.sh - MÓDULO 03 (MODS)
# Importação de configuração de Mods DSM
# Responsável por:
# - importar pacote DSM Mods
# - restaurar configuração
# - restaurar estado
# - preparar migração
# NÃO FAZ:
# - SteamCMD
# - instalação
# - rsync
# - keys
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

source "${DSM_ROOT}/core/bootstrap.sh"

# Garantia do logger
if ! declare -F log_error >/dev/null
then
    if [ -f "${DSM_ROOT}/core/logger.sh" ]
    then
        source "${DSM_ROOT}/core/logger.sh"
    fi
fi

# =============================================================
# Variáveis
# =============================================================
IMPORT_DIR="${DSM_ROOT}/import"
IMPORT_TMP="${IMPORT_DIR}/mods_import_tmp"
CONFIG_DIR="${DSM_ROOT}/config"
STATE_DIR="${DSM_ROOT}/state"

# =============================================================
# Preparar
# =============================================================
mods_import_prepare()
{
    rm -rf "${IMPORT_TMP}"
    mkdir -p "${IMPORT_TMP}"
}

# =============================================================
# Listar imports
# =============================================================
mods_import_list()
{
    mkdir -p "${IMPORT_DIR}"
    find "${IMPORT_DIR}" \
        -maxdepth 1 \
        -name "*.tar.gz" \
        -type f \
        -printf "%f\n" \
        2>/dev/null \
        | sort -r
}

# =============================================================
# Validar arquivo
# =============================================================
mods_import_validate_file()
{
    local file="$1"
    if [ -z "${file}" ]
    then
        log_error \
        "Arquivo de importação não informado."
        return 1
    fi

    if [ ! -f "${file}" ]
    then
        file="${IMPORT_DIR}/${file}"
    fi

    if [ ! -f "${file}" ]
    then
        log_error \
        "Arquivo não encontrado: ${file}"
        return 1
    fi

    echo "${file}"
}

# =============================================================
# Extrair pacote
# =============================================================
mods_import_extract()
{
    local file="$1"
    tar \
        -xzf "${file}" \
        -C "${IMPORT_TMP}"

    if [ "$?" -ne 0 ]
    then
        log_error \
        "Falha extraindo pacote."
        return 1
    fi
}

# =============================================================
# Validar manifesto
# =============================================================
mods_import_manifest()
{
    if [ ! -f "${IMPORT_TMP}/manifest.json" ]
    then
        log_error \
        "Manifesto ausente."
        return 1
    fi

    if command -v jq >/dev/null
    then
        local module
        module=$(jq -r '.module // empty' \
            "${IMPORT_TMP}/manifest.json")
        if [ "${module}" != "mods" ]
        then
            log_error \
            "Pacote inválido."
            return 1
        fi
    fi
}

# =============================================================
# Restaurar configuração
# =============================================================
mods_import_config()
{
    mkdir -p "${CONFIG_DIR}"
    if [ -f "${IMPORT_TMP}/config/dsm.conf" ]
    then
        cp \
        "${IMPORT_TMP}/config/dsm.conf" \
        "${CONFIG_DIR}/dsm.conf"
        log_info \
        "dsm.conf restaurado."
    fi

    if [ -f "${IMPORT_TMP}/config/workshop.conf" ]
    then
        source \
        "${IMPORT_TMP}/config/workshop.conf"
        export WORKSHOP_IDS
        log_info \
        "WORKSHOP_IDS restaurado."
    fi
}

# =============================================================
# Restaurar estado
# =============================================================
mods_import_state()
{
    if [ -d "${IMPORT_TMP}/state" ]
    then
        mkdir -p "${STATE_DIR}"
        cp -a \
        "${IMPORT_TMP}/state/"* \
        "${STATE_DIR}/"
        log_info \
        "Estado restaurado."
    fi
}

# =============================================================
# Pendência
# =============================================================
mods_import_pending()
{
mkdir -p "${STATE_DIR}"
cat > "${STATE_DIR}/mods_import_pending" <<EOF
DSM Mods Import concluído.

Execute:

dsm mods install

EOF
}

mods_import_apply()
{
local SRC="${IMPORT_TMP}"
log_info "Aplicando importação de mods..."

if [[ -d "${SRC}/mods" ]]
then
    mkdir -p "${MODS_DIR}"
    rsync -a \
        "${SRC}/mods/" \
        "${MODS_DIR}/"
fi

if [[ -d "${SRC}/keys" ]]
then
    mkdir -p "${KEYS_DIR}"
    rsync -a \
        "${SRC}/keys/" \
        "${KEYS_DIR}/"
fi

if [[ -f "${SRC}/state/mods.state" ]]
then
    mkdir -p "${STATE_DIR}"
    cp \
    "${SRC}/state/mods.state" \
    "${STATE_FILE}"
    log_info "Estado de mods restaurado."
fi

log_info "Importação aplicada."
}

# =============================================================
# Importação principal
# =============================================================
mods_import_run()
{
local input="${1:-}"

# =============================================================
# Modo automático
# =============================================================
if [[ "${input}" == "import" ]]
then
    input=""
fi

mods_import_prepare

# =============================================================
# Buscar arquivo informado
# =============================================================
local file
if [[ -n "${input}" ]]
then
    file=$(mods_import_validate_file "${input}")
else
    file=$(find \
        "${DSM_ROOT}/export" \
        -maxdepth 1 \
        -type f \
        -name "mods_export_*.tar.gz" \
        -printf "%T@ %p\n" \
        | sort -nr \
        | head -1 \
        | cut -d' ' -f2-)

    if [[ -z "${file}" ]]
    then
        log_error \
        "Nenhum pacote de importação encontrado."
        return 1
    fi
fi

log_info \
"Pacote encontrado:"
echo "${file}"

# =============================================================
# Extrair
# =============================================================
mods_import_extract "${file}"
mods_import_state

# =============================================================
# Restaurar
# =============================================================
mods_import_apply
log_info \
"Importação de mods concluída."
}

# =============================================================
# Wrapper DSM
# Chamado por:
# dsm mods import
# =============================================================
mods_import()
{
case "${1:-}" in
    "")
        echo
        echo "Uso:"
        echo
        echo " dsm mods import arquivo.tar.gz"
        echo " dsm mods import list"
        return 1
    ;;
    list)
        mods_import_list
    ;;
    run)
        shift
        mods_import_run "$@"
    ;;
    *)
        mods_import_run "$@"
    ;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    mods_import "$@"
fi
