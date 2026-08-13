#!/bin/bash
# =============================================================
# backup/rotate.sh - MÓDULO 06 (BACKUP)
#
# Política de retenção de backups DSM.
#
# Responsável por:
#
# - remover backups antigos
# - remover checksum
# - remover manifestos
# - registrar evento
#
# =============================================================


LOG_MODULE="backup"






rotate_run()
{


    section \
    "Rotação de backups"





    if [ ! -d "$BACKUP_DIR" ]
    then

        log_warn \
        "Diretório de backup não encontrado: $BACKUP_DIR"

        return 0

    fi






    if [ -z "$BACKUP_RETENTION_DAYS" ]
    then

        log_error \
        "BACKUP_RETENTION_DAYS não configurado"

        return 1

    fi






    if ! [[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]]
    then

        log_error \
        "BACKUP_RETENTION_DAYS inválido: $BACKUP_RETENTION_DAYS"

        return 1

    fi







    if ! lock_acquire "backup_rotate"
    then

        log_warn \
        "Rotação de backup já está em execução"

        return 1

    fi






    local removed=0







    while IFS= read -r -d '' old
    do


        rm -f \
        "$old" \
        "${old}.sha256" \
        "${old%.tar.gz}.manifest" \
        "${old}.manifest"



        removed=$((removed + 1))



    done < <(

        find "$BACKUP_DIR" \
        -maxdepth 1 \
        -type f \
        -name "backup_${INSTANCE_NAME}_*.tar.gz" \
        -mtime "+${BACKUP_RETENTION_DAYS}" \
        -print0

    )








    lock_release "backup_rotate"







    if [ "$removed" -gt 0 ]
    then


        log_ok \
        "$removed backup(s) removido(s) pela política de retenção (${BACKUP_RETENTION_DAYS} dias)"



        events_emit \
        "backup.rotated" \
        "$removed backup(s) removido(s)"



    else


        log_info \
        "Nenhum backup expirado encontrado"



    fi





    return 0

}
