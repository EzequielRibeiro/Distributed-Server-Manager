#!/bin/bash
# =============================================================
# backup/snapshot.sh - MÓDULO 06 (BACKUP)
#
# Snapshot do servidor DayZ
#
# Inclui:
#
# - mpmissions
# - serverDZ.cfg
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
# Variáveis
# =============================================================


SNAPSHOT_DIR="${BACKUP_DIR}/snapshots"



SNAPSHOT_DATE=$(date +"%Y%m%d-%H%M%S")



SNAPSHOT_PATH="${SNAPSHOT_DIR}/snapshot-${SNAPSHOT_DATE}"



# =============================================================
# Validar servidor
# =============================================================


snapshot_validate()
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
# Preparar snapshot
# =============================================================


snapshot_prepare()
{


    mkdir -p \
        "${SNAPSHOT_PATH}"


}



# =============================================================
# Criar snapshot
# =============================================================


snapshot_create()
{


    snapshot_validate || return 1



    snapshot_prepare



    log_info \
    "Criando snapshot DayZ..."



    # ---------------------------------------------------------
    # Configuração DayZ
    # ---------------------------------------------------------


    if [ -f "${SERVERFILES_PATH}/serverDZ.cfg" ]
    then


        cp \
        "${SERVERFILES_PATH}/serverDZ.cfg" \
        "${SNAPSHOT_PATH}/"



    fi



    # ---------------------------------------------------------
    # Missões
    # ---------------------------------------------------------


    if [ -d "${SERVERFILES_PATH}/mpmissions" ]
    then


        rsync -a \
        "${SERVERFILES_PATH}/mpmissions/" \
        "${SNAPSHOT_PATH}/mpmissions/"



    fi



    # ---------------------------------------------------------
    # Mods
    # ---------------------------------------------------------


    if [ -d "${SERVERFILES_PATH}/mods" ]
    then


        rsync -a \
        "${SERVERFILES_PATH}/mods/" \
        "${SNAPSHOT_PATH}/mods/"



    fi



    # ---------------------------------------------------------
    # Keys
    # ---------------------------------------------------------


    if [ -d "${SERVERFILES_PATH}/keys" ]
    then


        rsync -a \
        "${SERVERFILES_PATH}/keys/" \
        "${SNAPSHOT_PATH}/keys/"



    fi



    log_success \
    "Snapshot criado:"


    echo "${SNAPSHOT_PATH}"



}



# =============================================================
# Restaurar snapshot
# =============================================================


snapshot_restore()
{


    local source="$1"



    if [ ! -d "${source}" ]
    then


        log_error \
        "Snapshot não encontrado:"


        echo "${source}"


        return 1


    fi



    log_warning \
    "Restaurando snapshot..."



    rsync -a \
    "${source}/" \
    "${SERVERFILES_PATH}/"



    log_success \
    "Snapshot restaurado."



}



# =============================================================
# Listar snapshots
# =============================================================


snapshot_list()
{


    if [ ! -d "${SNAPSHOT_DIR}" ]
    then

        echo "Nenhum snapshot encontrado."

        return

    fi



    find "${SNAPSHOT_DIR}" \
        -maxdepth 1 \
        -type d \
        -name "snapshot-*" \
        -printf "%f\n"



}



# =============================================================
# Execução
# =============================================================


case "${1:-create}" in


    create)

        snapshot_create

    ;;


    restore)

        snapshot_restore "$2"

    ;;


    list)

        snapshot_list

    ;;


    *)

        echo "Uso:"
        echo
        echo " snapshot.sh create"
        echo " snapshot.sh list"
        echo " snapshot.sh restore CAMINHO"

    ;;


esac