#!/bin/bash
# =============================================================
# backup/create.sh - MÓDULO 06 (BACKUP)
#
# Criação de backup do servidor DayZ
#
# Inclui:
#
# - serverDZ.cfg
# - mpmissions
# - mods
# - keys
# - arquivos administrativos
#
# Fonte única:
#
#   /opt/dsm/config/dsm.conf
#
# Não utiliza:
#
#   settings.conf
#   LGSM_DIR
#
# =============================================================


LOG_MODULE="backup"


# =============================================================
# Ambiente DSM
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


if [[ -f "${DSM_ROOT}/core/bootstrap.sh" ]]
then
    # shellcheck source=/dev/null
    source "${DSM_ROOT}/core/bootstrap.sh"
fi

# Garantir logger
if ! declare -F log_info >/dev/null
then

    if [[ -f "${DSM_ROOT}/core/logger.sh" ]]
    then
        # shellcheck source=/dev/null
        source "${DSM_ROOT}/core/logger.sh"
    fi

fi
# =============================================================
# Configuração DSM
# =============================================================

DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"


if [[ ! -f "${DSM_CONFIG}" ]]
then

    echo "Configuração não encontrada:"
    echo "${DSM_CONFIG}"

    exit 1

fi


source "${DSM_CONFIG}"


# =============================================================
# Variáveis
# =============================================================


BACKUP_DIR="${BACKUP_DIR:-${DSM_BACKUP_DIR:-/opt/dsm-backup}}"



BACKUP_DATE=$(date +"%Y%m%d-%H%M%S")



BACKUP_FILE="${BACKUP_DIR}/dayz-backup-${BACKUP_DATE}.tar.gz"



# =============================================================
# Validar servidor
# =============================================================


backup_validate()
{

    if [ ! -d "${SERVERFILES_PATH}" ]
    then


        log_error \
        "Serverfiles não encontrado:"


        echo "${SERVERFILES_PATH}"


        return 1


    fi



}



# =============================================================
# Criar diretório backup
# =============================================================


backup_prepare()
{

    mkdir -p "${BACKUP_DIR}"

}



# =============================================================
# Criar backup
# =============================================================


backup_create()
{


    backup_validate || return 1


    backup_prepare



    log_info \
    "Criando backup DayZ..."



    tar \
        --dereference \
        -czf "${BACKUP_FILE}" \
        -C "${SERVERFILES_PATH}" \
        serverDZ.cfg \
        mpmissions \
        mods \
        keys \
        2>/dev/null



    if [ $? -ne 0 ]
    then


        log_error \
        "Falha ao criar backup."


        return 1


    fi



    log_success \
    "Backup criado:"


    echo "${BACKUP_FILE}"



    return 0


}



# =============================================================
# Listar backups
# =============================================================


backup_list()
{


    if [ ! -d "${BACKUP_DIR}" ]
    then

        echo "Nenhum backup encontrado."

        return

    fi



    ls -lh \
    "${BACKUP_DIR}"/*.tar.gz \
    2>/dev/null || true



}



# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    case "${1:-}" in


        create)

            backup_create

        ;;


        list)

            backup_list

        ;;


        *)

            echo "Uso:"
            echo
            echo " backup/create.sh create"
            echo " backup/create.sh list"

            exit 1

        ;;

    esac

fi