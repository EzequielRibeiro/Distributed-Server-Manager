#!/bin/bash
# =============================================================
# backup/restore.sh - MÓDULO 06 (BACKUP)
#
# Restauração de backup DayZ
#
# Restaura:
#
# - serverDZ.cfg
# - mpmissions
# - mods
# - keys
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
# Carregar configuração DSM
# =============================================================


if [ -z "${DSM_ROOT:-}" ]
then

    echo "DSM_ROOT não definido." >&2

    exit 1

fi



DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"



if [ ! -f "${DSM_CONFIG}" ]
then

    echo "Configuração não encontrada:"
    echo "${DSM_CONFIG}"

    exit 1

fi



# shellcheck source=/dev/null
source "${DSM_CONFIG}"



# =============================================================
# Validar parâmetros
# =============================================================


if [ -z "${1:-}" ]
then

    echo "Uso:"
    echo
    echo "restore.sh arquivo_backup.tar.gz"

    exit 1

fi



BACKUP_FILE="$1"



# =============================================================
# Verificar backup
# =============================================================


validate_backup()
{


    if [ ! -f "${BACKUP_FILE}" ]
    then


        log_error \
        "Backup não encontrado:"


        echo "${BACKUP_FILE}"


        return 1


    fi



    if ! tar -tzf "${BACKUP_FILE}" >/dev/null 2>&1
    then


        log_error \
        "Arquivo de backup inválido."


        return 1


    fi



    return 0

}



# =============================================================
# Criar backup de segurança antes da restauração
# =============================================================


create_pre_restore_backup()
{


    local date

    date=$(date +"%Y%m%d-%H%M%S")



    local safety_backup


    safety_backup="${BACKUP_DIR}/before-restore-${date}.tar.gz"



    log_info \
    "Criando backup de segurança..."



    tar \
        -czf "${safety_backup}" \
        -C "${SERVERFILES_PATH}" \
        serverDZ.cfg \
        mpmissions \
        mods \
        keys \
        2>/dev/null || true



    log_success \
    "Backup de segurança criado:"


    echo "${safety_backup}"


}



# =============================================================
# Restaurar backup
# =============================================================


restore_backup()
{


    validate_backup || return 1



    if [ ! -d "${SERVERFILES_PATH}" ]
    then


        log_error \
        "Serverfiles não encontrado:"


        echo "${SERVERFILES_PATH}"


        return 1


    fi



    create_pre_restore_backup



    log_warning \
    "Restaurando backup DayZ..."



    tar \
        -xzf "${BACKUP_FILE}" \
        -C "${SERVERFILES_PATH}"



    if [ $? -ne 0 ]
    then


        log_error \
        "Falha durante restauração."


        return 1


    fi



    log_success \
    "Restauração concluída."



    echo

    echo "Destino:"
    echo "${SERVERFILES_PATH}"



}



# =============================================================
# Execução
# =============================================================


restore_backup