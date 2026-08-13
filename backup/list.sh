#!/bin/bash
# =============================================================
# backup/list.sh - MÓDULO 06 (BACKUP)
#
# Listagem de backups DSM.
#
# Responsável por:
#
# - listar backups existentes
# - mostrar tamanho
# - validar checksum
# - gerar saída JSON para dashboard
#
# =============================================================


LOG_MODULE="backup"





# =============================================================
# Lista arquivos de backup
#
# Uso:
#
# list_backups
#
# Retorna:
#
# caminhos completos dos backups
#
# =============================================================


list_backups()
{

    if [ -z "$BACKUP_DIR" ]; then

        return 1

    fi





    [ -d "$BACKUP_DIR" ] || return 0





    find "$BACKUP_DIR" \
    -maxdepth 1 \
    -type f \
    -name "backup_${INSTANCE_NAME}_*.tar.gz" \
    -printf "%T@ %p\n" 2>/dev/null |
    sort -nr |
    cut -d' ' -f2-

}









# =============================================================
# Lista no terminal
# =============================================================


list_run()
{

    section "Backups disponíveis"





    local backups


    mapfile -t backups < <(list_backups)





    if [ "${#backups[@]}" -eq 0 ]; then


        log_warn \
        "Nenhum backup encontrado em $BACKUP_DIR"


        return 0

    fi







    printf "%-45s %-10s %-10s\n" \
    "ARQUIVO" \
    "TAMANHO" \
    "CHECKSUM"





    for b in "${backups[@]}"; do


        local size
        local chk





        size=$(du -h "$b" 2>/dev/null | awk '{print $1}')





        if checksum_verify "$b" >/dev/null 2>&1; then

            chk="OK"

        else

            chk="FALHA"

        fi





        printf "%-45s %-10s %-10s\n" \
        "$(basename "$b")" \
        "$size" \
        "$chk"



    done


    return 0

}









# =============================================================
# JSON Dashboard
# =============================================================


list_json()
{


    local backups


    mapfile -t backups < <(list_backups)





    if command -v jq >/dev/null 2>&1; then



        printf '%s\n' "${backups[@]}" |
        jq -R -s '
        split("\n")
        | map(select(length>0))
        | map({
            file: .,
            name: (. | split("/")[-1])
          })
        '



        return 0


    fi







    # Fallback sem jq


    echo "["


    local first=1



    for b in "${backups[@]}"; do


        [ "$first" -eq 0 ] && echo ","


        first=0



        printf \
        '{"file":"%s","size":"%s"}' \
        "$(basename "$b")" \
        "$(du -h "$b" 2>/dev/null | awk '{print $1}')"


    done



    echo "]"



}
