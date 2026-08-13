#!/bin/bash
# =============================================================
# mods/export.sh - MÓDULO 03 (MODS)
# Exportação de configuração de Mods DSM
# Responsável por:
# - exportar configuração
# - exportar estado
# - gerar manifesto
# - preparar migração
# NÃO FAZ:
# - download
# - SteamCMD
# - instalação
# - sincronização
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

# =============================================================
# Dependências
# =============================================================
source "${DSM_ROOT}/mods/state.sh"
source "${DSM_ROOT}/mods/detector.sh"

# =============================================================
# Configuração
# =============================================================
EXPORT_DIR="${DSM_ROOT}/export"
EXPORT_TMP="${EXPORT_DIR}/mods_export_tmp"
MOD_EXPORT_FILE="mods_export_$(date +%Y%m%d_%H%M%S).tar.gz"

# =============================================================
# Preparar diretórios
# =============================================================
mods_export_prepare()
{
    rm -rf "${EXPORT_TMP}"
   mkdir -p \
       "${EXPORT_TMP}/config" \
       "${EXPORT_TMP}/state" \
       "${EXPORT_TMP}/report" \
       "${EXPORT_TMP}/mods" \
       "${EXPORT_TMP}/keys"
}

mods_export_files()
{
    log_info \
    "Exportando arquivos dos mods"

    if [ -d "${SERVERFILES_PATH}/mods" ]
    then
        rsync -a \
        "${SERVERFILES_PATH}/mods/" \
        "${EXPORT_TMP}/mods/"
    fi

    if [ -d "${SERVERFILES_PATH}/keys" ]
    then
        rsync -a \
        "${SERVERFILES_PATH}/keys/" \
        "${EXPORT_TMP}/keys/"
    fi
}

# =============================================================
# Exportar configuração
# =============================================================
mods_export_config()
{
    log_info \
    "Exportando configuração"

    cp \
    "${DSM_ROOT}/config/dsm.conf" \
    "${EXPORT_TMP}/config/"
}

# =============================================================
# Exportar WORKSHOP_IDS
# =============================================================
mods_export_workshop()
{
    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        WORKSHOP_IDS="$(
            mods_detect_or_load_workshop_ids || true
        )"
    fi

    cat > "${EXPORT_TMP}/config/workshop.conf" <<EOF
# DSM Mods Export

WORKSHOP_IDS="${WORKSHOP_IDS}"

EOF
}

# =============================================================
# Exportar estado
# =============================================================
mods_export_state()
{
    if [ -d "${DSM_ROOT}/state" ]
    then
        cp -a \
        "${DSM_ROOT}/state" \
        "${EXPORT_TMP}/"
    fi
}

# =============================================================
# Lista dos mods
# =============================================================
mods_export_list()
{
    mkdir -p \
    "${EXPORT_TMP}/report"

    {
        echo "DSM Mods Export"
        echo
        echo "Data:"
        date
        echo
        echo "Mods instalados:"
        echo

        find "${SERVERFILES_PATH}/mods" \
            -maxdepth 1 \
            -type d \
            -name "@*" \
            -printf "%f\n"
    } > "${EXPORT_TMP}/report/mods.txt"
}

# =============================================================
# Manifesto JSON
# =============================================================
mods_export_manifest()
{
cat > "${EXPORT_TMP}/manifest.json" <<EOF
{
    "module":"mods",
    "version":"1.0",
    "created":"$(date -Iseconds)",
    "server":"$(hostname)",
    "workshop_ids":"${WORKSHOP_IDS}"
}
EOF
}

# =============================================================
# Criar pacote
# =============================================================
mods_export_create()
{
    mods_export_prepare || return 1
    mods_export_config || return 1
    mods_export_workshop || return 1
    mods_export_state || return 1
    mods_export_files || return 1
    mods_export_list || return 1
    mods_export_manifest || return 1

    mkdir -p "${EXPORT_DIR}"

    local output
    output="${EXPORT_DIR}/${MOD_EXPORT_FILE}"

    tar \
        -czf "${output}" \
        -C "${EXPORT_TMP}" \
        .

    if [ "$?" -ne 0 ]
    then
        log_error \
        "Falha criando export."
        return 1
    fi

    rm -rf "${EXPORT_TMP}"

    log_ok \
    "Export criado:"
    echo "${output}"
}

# =============================================================
# Listar exports
# =============================================================
mods_export_list_files()
{
    find "${EXPORT_DIR}" \
        -name "mods_export_*.tar.gz" \
        -type f \
        -printf "%f\n" \
        2>/dev/null \
        | sort -r
}

# =============================================================
# Wrapper DSM CLI
# Compatibilidade:
# dsm mods export
# =============================================================
mods_export()
{
    local command="${1:-create}"
        case "${command}" in
        export)
            mods_export_create
        ;;
        create)
            mods_export_create
        ;;
        list)
            mods_export_list_files
        ;;
        *)
            echo
            echo "Uso:"
            echo
            echo " dsm mods export"
            echo " dsm mods export list"
            echo
            return 1
        ;;
        esac
}

# =============================================================
# Dispatcher interno
# =============================================================
export_command()
{
case "${1:-}" in
    create)
        mods_export_create
    ;;
    list)
        mods_export_list_files
    ;;
    *)
        echo
        echo "Uso:"
        echo
        echo " export.sh create"
        echo " export.sh list"
        return 1
    ;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    export_command "$@"
fi
