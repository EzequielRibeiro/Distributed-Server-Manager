#!/bin/bash
# =============================================================
# mods/status.sh - MÓDULO 03 (MODS)
# Status consolidado dos Mods DSM
# Responsável por:
# - mostrar estado dos mods
# - consultar configuração
# - exibir saúde básica
# NÃO FAZ:
# - instalação
# - atualização
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
source "${DSM_ROOT}/mods/validator.sh"

# =============================================================
# Variáveis
# =============================================================
MODS_DIR="${SERVERFILES_PATH}/mods"
BACKUP_DIR="${DSM_ROOT}/backup/mods"

# =============================================================
# Contadores
# =============================================================
mods_status_count()
{
    if [ ! -d "${MODS_DIR}" ]
    then
        echo 0
        return
    fi

    find "${MODS_DIR}" \
        -maxdepth 1 \
        -type d \
        -name "@*" \
        | wc -l
}

# =============================================================
# Verificar import pendente
# =============================================================
mods_status_import()
{
    if [ -f "${DSM_ROOT}/state/mods_import_pending" ]
    then
        echo "PENDENTE"
    else
        echo "OK"
    fi
}

# =============================================================
# Verificar backup
# =============================================================
mods_status_backup()
{
    if [ -d "${BACKUP_DIR}" ] &&
       find "${BACKUP_DIR}" \
       -type f \
       -name "*.tar.gz" \
       | grep -q .
    then
        echo "OK"
    else
        echo "NENHUM"
    fi
}

# =============================================================
# Status dos mods
# =============================================================
mods_status_show()
{
    section \
    "Status dos Mods DSM"

    local total
    total="$(mods_status_count)"

    echo "Mods instalados:"
    echo "${total}"
    echo

    echo "Workshop configurado:"
    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        WORKSHOP_IDS="$(mods_detect_or_load_workshop_ids || true)"
    fi

    echo "${WORKSHOP_IDS:-nenhum}"
    echo

    echo "Estado DSM:"
    if [ -d "${DSM_ROOT}/state" ]
    then
        echo "OK"
    else
        echo "INEXISTENTE"
    fi
    echo

    echo "Importação:"
    mods_status_import
    echo

    echo "Backup Mods:"
    mods_status_backup
    echo

    echo "Validação:"
    if mods_validate
    then
        echo "OK"
    else
        echo "ERRO"
    fi
}

# =============================================================
# Status JSON
# Uso Dashboard
# =============================================================
mods_status_json()
{
cat <<EOF
{
    "module":"mods",
    "installed":$(mods_status_count),
    "import":"$(mods_status_import)",
    "backup":"$(mods_status_backup)",
    "workshop":"${WORKSHOP_IDS:-}"
}
EOF
}

# =============================================================
# Dispatcher
# =============================================================
status_command()
{
case "${1:-}" in
    show)
        mods_status_show
    ;;
    json)
        mods_status_json
    ;;
    *)
        echo
        echo "Uso:"
        echo
        echo " status.sh show"
        echo " status.sh json"
        return 1
    ;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    status_command "$@"
fi
