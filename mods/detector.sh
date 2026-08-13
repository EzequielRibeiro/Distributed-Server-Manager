#!/bin/bash
# =============================================================
# mods/detector.sh - MÓDULO 03 (MODS)
#
# Detector de Mods DSM
# DSM Mods Detector
#
# Responsável por: | Responsible for:
# - detectar mods instalados manualmente | detecting manually installed mods
# - ler meta.cpp | reading meta.cpp
# - identificar Workshop ID | identifying Workshop ID
# - carregar WORKSHOP_IDS | loading WORKSHOP_IDS
# - atualizar dsm.conf | updating dsm.conf
#
# Não executa: | DOES NOT execute:
# - SteamCMD
# - rsync
# - keys
# - instalação | installation
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap DSM
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

BOOTSTRAP="${DSM_ROOT}/core/bootstrap.sh"
if [ ! -f "${BOOTSTRAP}" ]
then
    echo "Bootstrap não encontrado:"
    echo "Bootstrap not found:"
    echo "${BOOTSTRAP}"
    exit 1
fi

# shellcheck source=/dev/null
source "${BOOTSTRAP}"

# =============================================================
# Configuração | Configuration
# =============================================================
DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"
if [ ! -f "${DSM_CONFIG}" ]
then
    log_error \
    "Configuração DSM não encontrada."
    log_error \
    "DSM configuration not found."
    echo "${DSM_CONFIG}"
    exit 1
fi

# shellcheck source=/dev/null
source "${DSM_CONFIG}"

# =============================================================
# Diretórios | Directories
# =============================================================
MODS_DIR="${SERVERFILES_PATH}/mods"

# =============================================================
# Detectar Workshop IDs | Detect Workshop IDs
#
# Procura: | Searches:
# serverfiles/mods/@MOD/meta.cpp
#
# Conteúdo: | Content:
# publishedid = XXXXX;
#
# Retorno: | Return:
# ID:@MOD;ID:@MOD
# =============================================================
mods_detect_workshop_ids()
{
    local ids=()
    if [ ! -d "${MODS_DIR}" ]
    then
        log_warn \
        "Diretório de Mods não encontrado."
        log_warn \
        "Mods directory not found."
        return 1
    fi

    while IFS= read -r meta
    do
        local folder
        local id

        # Nome da pasta @MOD | @MOD folder name
        folder="$(
            basename \
            "$(dirname "${meta}")"
        )"

        # Extrair publishedid | Extract publishedid
        id="$(
            grep -Eo \
            'publishedid[[:space:]]*=[[:space:]]*[0-9]+' \
            "${meta}" \
            | grep -Eo '[0-9]+'
        )"

        if [ -n "${id}" ] &&
           [ -n "${folder}" ]
        then
            ids+=("${id}:${folder}")
        fi
    done < <(
        find -L "${MODS_DIR}" \
        -mindepth 2 \
        -maxdepth 2 \
        -name meta.cpp \
        2>/dev/null
    )

    if [ "${#ids[@]}" -eq 0 ]
    then
        return 1
    fi

    (
        IFS=";"
        echo "${ids[*]}"
    )
}

# =============================================================
# Atualizar WORKSHOP_IDS no dsm.conf
# Update WORKSHOP_IDS in dsm.conf
# =============================================================
mods_update_workshop_config()
{
    local ids="$1"
    if [ -z "${ids}" ]
    then
        log_error \
        "Nenhum Workshop ID informado."
        log_error \
        "No Workshop ID provided."
        return 1
    fi

    WORKSHOP_IDS="${ids}"
    export WORKSHOP_IDS

    if grep -q '^WORKSHOP_IDS=' "${DSM_CONFIG}"
    then
        sed -i \
        "s|^WORKSHOP_IDS=.*|WORKSHOP_IDS=\"${ids}\"|" \
        "${DSM_CONFIG}"
    else
        echo \
        "WORKSHOP_IDS=\"${ids}\"" \
        >> "${DSM_CONFIG}"
    fi

    if grep -q '^WORKSHOP_IDS=' "${DSM_CONFIG}"
    then
        log_ok \
        "WORKSHOP_IDS atualizado | updated: ${ids}"
        return 0
    fi

    log_error \
    "Falha ao atualizar WORKSHOP_IDS."
    log_error \
    "Failed to update WORKSHOP_IDS."
    return 1
}

# =============================================================
# Detectar ou carregar configuração
# Detect or load configuration
#
# Ordem: | Order:
# 1 - dsm.conf
# 2 - mods existentes | existing mods
# =============================================================
mods_detect_or_load_workshop_ids()
{
    # Já existe configuração | Configuration already exists
    if [ -n "${WORKSHOP_IDS:-}" ]
    then
        log_ok \
        "WORKSHOP_IDS carregado da configuração." \
        >&2
        log_ok \
        "WORKSHOP_IDS loaded from configuration." \
        >&2
        return 0
    fi

    log_warn \
    "WORKSHOP_IDS vazio. Detectando mods instalados." \
    >&2
    log_warn \
    "WORKSHOP_IDS empty. Detecting installed mods." \
    >&2

    local detected
    detected="$(
        mods_detect_workshop_ids || true
    )"

    if [ -z "${detected}" ]
    then
        log_error \
        "Nenhum mod detectado." \
        >&2
        log_error \
        "No mods detected." \
        >&2
        return 1
    fi

    log_info \
    "Mods detectados | detected: ${detected}" \
    >&2

    mods_update_workshop_config \
        "${detected}"
}

# =============================================================
# Listar mods detectados | List detected mods
# =============================================================
mods_detector_list()
{
    local ids
    ids="$(mods_detect_workshop_ids || true)"

    if [ -z "${ids}" ]
    then
        echo "Nenhum mod encontrado | No mods found."
        return 1
    fi
    echo "${ids}"
}

# =============================================================
# Dispatcher
# =============================================================
detector_command()
{
case "${1:-}" in
detect)
    mods_detect_workshop_ids
;;
sync)
    mods_detect_or_load_workshop_ids
;;
list)
    mods_detector_list
;;
*)
    echo
    echo "Uso | Usage:"
    echo
    echo " detector.sh detect"
    echo " detector.sh sync"
    echo " detector.sh list"
    return 1
;;
esac
}

# =============================================================
# Execução direta | Direct execution
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    detector_command "$@"
fi
