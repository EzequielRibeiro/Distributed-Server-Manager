#!/bin/bash
# =============================================================
# backup/checksum.sh - MÓDULO 06 (BACKUP)
#
# Geração e validação de checksum SHA256 dos backups DSM.
#
# Responsável por:
#
# - criar assinatura SHA256
# - validar integridade
# - detectar corrupção de backup
#
# =============================================================


LOG_MODULE="backup"





# =============================================================
# Gerar checksum
#
# Uso:
#
# checksum_generate arquivo.tar.gz
#
# Resultado:
#
# arquivo.tar.gz.sha256
#
# =============================================================


checksum_generate()
{

    local file="$1"



    if [ -z "$file" ]; then

        log_error "Arquivo não informado para checksum"

        return 1

    fi





    if [ ! -f "$file" ]; then

        log_error \
        "Arquivo não encontrado: $file"

        return 1

    fi





    if [ ! -s "$file" ]; then

        log_error \
        "Arquivo vazio, checksum cancelado: $file"

        return 1

    fi





    sha256sum "$file" > "${file}.sha256"





    if [ $? -ne 0 ]; then

        log_error \
        "Falha ao gerar checksum: $file"

        return 1

    fi





    log_ok \
    "Checksum criado: ${file}.sha256"



    return 0

}









# =============================================================
# Validar checksum
#
# Retorna:
#
# 0 = válido
# 1 = inválido
#
# Uso:
#
# checksum_verify arquivo.tar.gz
#
# =============================================================


checksum_verify()
{

    local file="$1"

    local sumfile="${file}.sha256"





    if [ -z "$file" ]; then

        log_error \
        "Arquivo não informado para validação"

        return 1

    fi





    if [ ! -f "$file" ]; then

        log_error \
        "Arquivo não encontrado: $file"

        return 1

    fi





    if [ ! -f "$sumfile" ]; then

        log_warn \
        "Checksum inexistente: $(basename "$file")"

        return 1

    fi







    (
        cd "$(dirname "$file")" || exit 1

        sha256sum \
        -c "$(basename "$sumfile")" \
        >/dev/null 2>&1

    )





    local rc=$?





    if [ "$rc" -eq 0 ]; then

        log_ok \
        "Checksum válido: $(basename "$file")"

    else

        log_error \
        "Checksum inválido: $(basename "$file")"

    fi





    return $rc

}
