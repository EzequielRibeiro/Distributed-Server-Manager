#!/bin/bash
# =============================================================
# mods/metadata.sh - MÓDULO 03 (MODS)
# Scanner de metadata dos mods DayZ
# Funções:
# - localizar mods instalados
# - ler meta.cpp
# - extrair publishedid
# - gerar WORKSHOP_IDS
# - sincronizar dsm.conf
# =============================================================

# =============================================================
# Ambiente DSM
# =============================================================
if [[ -z "${DSM_ROOT:-}" ]]
then
    DSM_ROOT="/opt/dsm"
    export DSM_ROOT
fi

# =============================================================
# Carregar configuração DSM
# =============================================================
DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"

if [[ -f "${DSM_CONFIG}" ]]
then
    # shellcheck source=/dev/null
    source "${DSM_CONFIG}"
else
    echo
    echo "Configuração DSM não encontrada:"
    echo "${DSM_CONFIG}"
    return 1 2>/dev/null || exit 1
fi

# =============================================================
# Helpers
# =============================================================
section()
{
    echo
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}

print_ok()
{
    printf "[OK] %s\n" "$1"
}

print_warn()
{
    printf "[WARNING] %s\n" "$1"
}

log_error()
{
    printf "[ERROR] %s\n" "$1"
}

# =============================================================
# Scanner Metadata
# =============================================================
mods_scan_metadata()
{
    section "Scanner de Mods"

    if [[ -z "${SERVERFILES_PATH:-}" ]]
    then
        log_error \
        "SERVERFILES_PATH não definido em dsm.conf"
        return 1
    fi

    local mods_dir
    mods_dir="${SERVERFILES_PATH}/mods"

    if [[ ! -d "${mods_dir}" ]]
    then
        log_error \
        "Diretório de mods não encontrado: ${mods_dir}"
        return 1
    fi

    local ids=()
    local count=0
    local found=0

    while IFS= read -r -d ''
    do
        local meta
        local mod_name
        local id
        meta="${REPLY}"
        mod_name="$(basename "$(dirname "${meta}")")"
        id="$(
            grep -E \
            'publishedid[[:space:]]*=' \
            "${meta}" |
            sed -E \
            's/.*publishedid[[:space:]]*=[[:space:]]*([0-9]+).*/\1/'
        )"

        if [[ -n "${id}" ]]
        then
            printf "%-35s %s\n" \
            "${mod_name}" \
            "${id}"

            ids+=("${id}")
            found=$((found+1))
        else
            print_warn \
            "${mod_name}: publishedid não encontrado"
        fi
        count=$((count+1))
    done < <(
        find -L "${mods_dir}" \
            -mindepth 2 \
            -maxdepth 3 \
            -type f \
            -name "meta.cpp" \
            -print0
    )

    echo

    if (( count == 0 ))
    then
        print_warn "Nenhum meta.cpp encontrado"
        return 1
    fi

    if (( found == 0 ))
    then
        print_warn "Nenhum publishedid encontrado"
        return 1
    fi

    # Criar WORKSHOP_IDS
    WORKSHOP_IDS="$(
        IFS=";"
        echo "${ids[*]}"
    )"
    export WORKSHOP_IDS

    echo
    print_ok "${found}/${count} mods com publishedid"
    return 0
}

# =============================================================
# Sincronizar dsm.conf
# =============================================================
mods_sync_workshop_ids()
{
    if [[ -z "${WORKSHOP_IDS:-}" ]]
    then
        print_warn \
        "WORKSHOP_IDS vazio"
        return 1
    fi

    if grep -q '^WORKSHOP_IDS=' "${DSM_CONFIG}"
    then
        sed -i \
        "s|^WORKSHOP_IDS=.*|WORKSHOP_IDS=\"${WORKSHOP_IDS}\"|" \
        "${DSM_CONFIG}"
    else
        echo \
        "WORKSHOP_IDS=\"${WORKSHOP_IDS}\"" \
        >> "${DSM_CONFIG}"
    fi

    print_ok \
    "WORKSHOP_IDS sincronizado"
    return 0
}

# =============================================================
# Comando completo
# =============================================================
mods_metadata_sync()
{
    mods_scan_metadata || return 1
    mods_sync_workshop_ids || return 1
    return 0
}

# =============================================================
# Exportar funções
# =============================================================
export -f mods_scan_metadata
export -f mods_sync_workshop_ids
export -f mods_metadata_sync

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    mods_metadata_sync
fi
