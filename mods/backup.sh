#!/bin/bash
# =============================================================
# mods/backup.sh - MÓDULO 03 (MODS)
# Backup e Restore de Mods DSM
# Responsável por:
# - criar backup dos mods
# - listar backups
# - restaurar backup
# - rotacionar backups antigos
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap DSM
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Configuração
# =============================================================
DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"

if [ -f "${DSM_CONFIG}" ]
then
    source "${DSM_CONFIG}"
fi

SERVERFILES_PATH="${SERVERFILES_PATH:-${DSM_HOME}/serverfiles}"
MODS_DIR="${SERVERFILES_PATH}/mods"
KEYS_DIR="${SERVERFILES_PATH}/keys"
MOD_BACKUP_DIR="${DSM_ROOT}/backup/mods"

# =============================================================
# Preparar backup
# =============================================================
mods_backup_prepare()
{
    mkdir -p \
        "${MOD_BACKUP_DIR}"

    if [ ! -d "${MOD_BACKUP_DIR}" ]
    then
        log_error \
        "Falha criando diretório de backup."
        return 1
    fi
}

# =============================================================
# Nome do backup
# =============================================================
mods_backup_name()
{
    date +"mods-%Y%m%d-%H%M%S.tar.gz"
}

# =============================================================
# Criar backup
# =============================================================
mods_backup_create()
{
    mods_backup_prepare || return 1
    if [ ! -d "${MODS_DIR}" ]
    then
        log_error \
        "Diretório de mods não encontrado."
        return 1
    fi

    local file
    file="${MOD_BACKUP_DIR}/$(mods_backup_name)"

    section \
    "Criando backup de Mods"

    tar \
        -czf "${file}" \
        -C "${SERVERFILES_PATH}" \
        mods \
        keys

    if [ $? -ne 0 ]
    then
        log_error \
        "Falha criando backup."
        return 1
    fi

    log_ok \
    "Backup criado: ${file}"

    echo "${file}"
}

# =============================================================
# Listar backups
# =============================================================
mods_backup_list()
{
    mods_backup_prepare || return 1
    section \
    "Backups de Mods"

    local count=0
    while IFS= read -r file
    do
        echo "${file}"
        count=$((count+1))
    done < <(
        find "${MOD_BACKUP_DIR}" \
        -type f \
        -name "mods-*.tar.gz" \
        | sort
    )

    if [ "${count}" -eq 0 ]
    then
        echo
        echo "Nenhum backup encontrado."
    fi
}

# =============================================================
# Restaurar backup
# =============================================================
mods_backup_restore()
{
    local file="$1"
    if [ -z "${file}" ]
    then
        log_error \
        "Informe backup."
        return 1
    fi

    if [ ! -f "${file}" ]
    then
        log_error \
        "Backup não encontrado: ${file}"
        return 1
    fi

    section \
    "Restaurando Mods"

    tar \
        -xzf "${file}" \
        -C "${SERVERFILES_PATH}"

    if [ $? -ne 0 ]
    then
        log_error \
        "Falha restaurando backup."
        return 1
    fi

    log_ok \
    "Backup restaurado."
}

# =============================================================
# Rotacionar backups
# =============================================================
mods_backup_rotate()
{
    mods_backup_prepare || return 1
    local keep="${1:-5}"
    local total
    total=$(
        find "${MOD_BACKUP_DIR}" \
        -name "mods-*.tar.gz" \
        | wc -l
    )

    if [ "${total}" -le "${keep}" ]
    then
        log_info \
        "Nenhuma rotação necessária."
        return 0
    fi

    find "${MOD_BACKUP_DIR}" \
        -name "mods-*.tar.gz" \
        | sort \
        | head -n "-${keep}" \
        | while read -r old
        do
            rm -f "${old}"
            log_ok \
            "Removido backup antigo: ${old}"
        done
}

# =============================================================
# Wrapper DSM
# Compatibilidade:
# dsm mods backup
# =============================================================
mods_backup()
{
    case "${1:-create}" in
    create)
        mods_backup_create
    ;;
    list)
        mods_backup_list
    ;;
    restore)
        shift
        mods_backup_restore "$@"
    ;;
    rotate)
        shift
        mods_backup_rotate "$@"
    ;;
    *)
        echo
        echo "Uso:"
        echo
        echo " dsm mods backup"
        echo " dsm mods backup list"
        echo " dsm mods backup restore arquivo"
        echo " dsm mods backup rotate quantidade"
        return 1
    ;;
    esac
}
