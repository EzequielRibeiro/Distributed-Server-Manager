#!/bin/bash
# =============================================================
# backup/manifest.sh - MÓDULO 06 (BACKUP)
#
# Gera e consulta manifesto dos backups DSM.
#
# Responsável por:
#
# - listar arquivos internos do backup
# - registrar tamanho
# - registrar data de criação
# - auxiliar diagnóstico/restauração
#
# =============================================================


LOG_MODULE="backup"





# =============================================================
# Gerar manifesto
#
# Uso:
#
# manifest_generate arquivo.tar.gz arquivo.manifest
#
# =============================================================


manifest_generate()
{

    local tarball="$1"
    local manifest_path="$2"





    if [ -z "$tarball" ] || [ -z "$manifest_path" ]; then

        log_error \
        "Parâmetros insuficientes para gerar manifesto"

        return 1

    fi





    if [ ! -f "$tarball" ]; then

        log_error \
        "Backup não encontrado: $tarball"

        return 1

    fi





    mkdir -p "$(dirname "$manifest_path")"





    {

        echo "# =================================================="
        echo "# Manifesto DSM Backup"
        echo "# =================================================="
        echo ""
        echo "Arquivo: $(basename "$tarball")"
        echo "Gerado em: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "Tamanho: $(du -h "$tarball" 2>/dev/null | awk '{print $1}')"
        echo ""
        echo "# Conteúdo"
        echo ""

        tar -tzvf "$tarball" 2>/dev/null


    } > "$manifest_path"





    if [ $? -ne 0 ]; then

        log_error \
        "Falha ao gerar manifesto: $manifest_path"

        return 1

    fi





    log_ok \
    "Manifesto criado: $(basename "$manifest_path")"



    return 0

}









# =============================================================
# Exibir manifesto
#
# Uso:
#
# manifest_show arquivo.manifest
#
# =============================================================


manifest_show()
{

    local manifest_path="$1"





    if [ -z "$manifest_path" ]; then

        log_error \
        "Manifesto não informado"

        return 1

    fi





    if [ ! -f "$manifest_path" ]; then

        log_warn \
        "Manifesto não encontrado: $manifest_path"

        return 1

    fi





    cat "$manifest_path"



    return 0

}
