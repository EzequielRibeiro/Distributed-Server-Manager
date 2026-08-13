#!/bin/bash
# =============================================================
# mods/cleanup.sh - MÓDULO 03 (MODS)
# Limpeza de arquivos temporários dos Mods
# Responsável por:
# - limpar arquivos temporários
# - remover resíduos SteamCMD
# - verificar antes de apagar
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
# Configuração DSM
# =============================================================
DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"

if [ -f "${DSM_CONFIG}" ]
then
    source "${DSM_CONFIG}"
fi

# =============================================================
# Defaults
# =============================================================
STEAMCMD_DIR="${STEAMCMD_DIR:-${DSM_HOME}/steamcmd}"
SERVERFILES_PATH="${SERVERFILES_PATH:-${DSM_HOME}/serverfiles}"
MODS_DIR="${SERVERFILES_PATH}/mods"
WORKSHOP_DIR="${STEAMCMD_DIR}/steamapps/workshop"

# =============================================================
# Limpeza
# =============================================================
mods_cleanup()
{
    local dry_run="false"
    if [ "${1:-}" = "--dry-run" ]
    then
        dry_run="true"
        log_info \
        "Executando limpeza simulada."
    fi

    log_info \
    "Iniciando limpeza de Mods."

    local targets=()

    # Arquivos temporários
    while IFS= read -r file
    do
        targets+=("${file}")
    done < <(
        find "${MODS_DIR}" \
        -type f \
        \( \
            -name "*.tmp" \
            -o \
            -name "*.bak" \
        \) \
        2>/dev/null
    )

    # Downloads incompletos SteamCMD
    while IFS= read -r file
    do
        targets+=("${file}")
    done < <(
        find "${WORKSHOP_DIR}" \
        -type f \
        -name "*.part" \
        2>/dev/null
    )

    if [ "${#targets[@]}" -eq 0 ]
    then
        log_ok \
        "Nenhum arquivo temporário encontrado."
        return 0
    fi

    local count=0
    for file in "${targets[@]}"
    do
        if [ "${dry_run}" = "true" ]
        then
            echo "[DRY-RUN] ${file}"
        else
            rm -f \
            "${file}"

            if [ $? -eq 0 ]
            then
                count=$((count+1))
                log_ok \
                "Removido: ${file}"
            fi
        fi
    done

    if [ "${dry_run}" = "true" ]
    then
        log_ok \
        "Limpeza simulada concluída: ${#targets[@]} arquivos."
    else
        log_ok \
        "Limpeza concluída: ${count} arquivos removidos."
    fi

    return 0
}

# =============================================================
# Dispatcher standalone
# =============================================================
cleanup_command()
{
case "${1:-}" in
--dry-run)
    mods_cleanup --dry-run
;;
*)
    mods_cleanup
;;
esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]
then
    cleanup_command "$@"
fi
