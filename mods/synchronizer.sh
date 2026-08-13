#!/bin/bash
# =============================================================
# mods/synchronizer.sh - MÓDULO 03 (MODS)
# Sincronização Workshop -> Mods
# Responsável por:
#  - copiar Workshop para mods/@MOD
#  - remover arquivos antigos
#  - preservar estrutura do mod
#  - sincronizar keys após atualização
# Fluxo:
# steamcmd.sh
#      |
#      v
# Workshop Content
#      |
#      v
# synchronizer.sh
#      |
#      v
# serverfiles/mods/@MOD
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap DSM
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

# shellcheck source=/dev/null
source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Dependências
# =============================================================
# shellcheck source=/dev/null
source "${DSM_ROOT}/mods/steamcmd.sh"

# shellcheck source=/dev/null
source "${DSM_ROOT}/mods/keys.sh"

# =============================================================
# Diretórios
# =============================================================
MODS_DIR="${SERVERFILES_PATH}/mods"

# =============================================================
# Sincronizar um mod
# Uso:
# mods_sync_one WORKSHOP_ID @MOD
# =============================================================
mods_sync_one()
{
    local workshop_id="$1"
    local folder="$2"
    local source
    local target

    if [ -z "${workshop_id}" ] ||
       [ -z "${folder}" ]
    then
        log_error \
        "Uso: mods_sync_one WORKSHOP_ID @MOD"
        return 1
    fi

    source="$(steamcmd_item_path "${workshop_id}")"
    target="${MODS_DIR}/${folder}"

    if [ ! -d "${source}" ]
    then
        log_error \
        "Workshop não encontrado:"
        echo "${source}"
        return 1
    fi

    mkdir -p "${target}"

    log_info \
    "Sincronizando ${folder}"

    rsync \
        -a \
        --delete \
        --checksum \
        "${source}/" \
        "${target}/"

    local rc=$?
    if [ "${rc}" -ne 0 ]
    then
        log_error \
        "Falha rsync em ${folder}"
        return 1
    fi

    log_ok \
    "${folder} sincronizado"

    # Sincronizar keys após atualização
    if declare -F keys_sync_one >/dev/null
    then
        keys_sync_one \
            "${workshop_id}" \
            "${folder}"
    fi

    return 0
}

# =============================================================
# Alias compatibilidade
# Mantém chamadas antigas:
# mods_sync ID @MOD
# =============================================================
mods_sync()
{
    mods_sync_one \
        "$1" \
        "$2"
}

# =============================================================
# Sincronizar todos os mods
# Usa:
# WORKSHOP_IDS
# Formato:
# ID:@MOD;ID:@MOD
# =============================================================
mods_sync_all()
{
    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        log_error \
        "WORKSHOP_IDS não definido."
        return 1
    fi

    IFS=';' read -ra MOD_LIST <<< "${WORKSHOP_IDS}"
    local item
    for item in "${MOD_LIST[@]}"
    do
        local id
        local folder
        id="${item%%:*}"
        folder="${item##*:}"
        id="$(echo "${id}" | xargs)"
        folder="$(echo "${folder}" | xargs)"
        [ -z "${id}" ] && continue

        mods_sync_one \
            "${id}" \
            "${folder}" || return 1
    done
    return 0
}

# =============================================================
# Dry Run
# Apenas mostra alterações
# =============================================================
mods_sync_dryrun()
{
    local id="$1"
    local folder="$2"

    rsync \
        -an \
        --delete \
        --checksum \
        "$(steamcmd_item_path "${id}")/" \
        "${MODS_DIR}/${folder}/"
}

# =============================================================
# Ajustar permissões
# =============================================================
mods_sync_permissions()
{
    chmod -R u+rwX \
        "${MODS_DIR}"

    find "${MODS_DIR}" \
        -type d \
        -exec chmod 755 {} \;

    find "${MODS_DIR}" \
        -type f \
        -exec chmod 644 {} \;

    log_ok \
    "Permissões dos mods ajustadas."
}

# =============================================================
# Validar sincronização
# =============================================================
mods_sync_validate()
{
    local folder="$1"
    if [ ! -d "${MODS_DIR}/${folder}" ]
    then
        return 1
    fi

    find "${MODS_DIR}/${folder}" \
        -mindepth 1 \
        -print \
        -quit \
        | grep -q .
}

# =============================================================
# Dispatcher
# =============================================================
synchronizer_command()
{
case "$1" in
    one)
        mods_sync_one \
            "$2" \
            "$3"
    ;;
    all)
        mods_sync_all
    ;;
    dryrun)
        mods_sync_dryrun \
            "$2" \
            "$3"
    ;;
    permissions)
        mods_sync_permissions
    ;;
    validate)
        mods_sync_validate \
            "$2"
    ;;
    *)
        echo
        echo "Uso:"
        echo
        echo " synchronizer.sh one WORKSHOP_ID @MOD"
        echo " synchronizer.sh all"
        echo " synchronizer.sh dryrun WORKSHOP_ID @MOD"
        echo " synchronizer.sh permissions"
        echo " synchronizer.sh validate @MOD"
        return 1
    ;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    synchronizer_command "$@"
fi
