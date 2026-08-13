#!/bin/bash
# =============================================================
# mods/pipeline.sh - MÓDULO 03 (MODS)
# Orquestrador do módulo de Mods DSM
# Responsável por:
# - instalação
# - atualização
# - validação
# - rollback
# Não executa:
# - SteamCMD
# - rsync
# - keys
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Carregar módulos
# =============================================================
source "${DSM_ROOT}/mods/steamcmd.sh"
source "${DSM_ROOT}/mods/synchronizer.sh"
source "${DSM_ROOT}/mods/keys.sh"
source "${DSM_ROOT}/mods/state.sh"
source "${DSM_ROOT}/mods/rollback.sh"
source "${DSM_ROOT}/mods/detector.sh"
source "${DSM_ROOT}/mods/updater.sh"
source "${DSM_ROOT}/mods/validator.sh"
source "${DSM_ROOT}/mods/installer.sh"
source "${DSM_ROOT}/mods/report.sh"
source "${DSM_ROOT}/mods/backup.sh"
source "${DSM_ROOT}/mods/status.sh"

# =============================================================
# Detectar Mods configurados
# Usa:
# dsm.conf
# WORKSHOP_IDS
# ou
# meta.cpp existente
# =============================================================
mods_pipeline_prepare()
{
    mods_prepare || return 1
    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        log_warn \
        "WORKSHOP_IDS não definido. Detectando mods instalados."
        WORKSHOP_IDS="$(mods_detect_workshop_ids || true)"
    fi

    if [ -z "${WORKSHOP_IDS:-}" ]
    then
        log_error \
        "Nenhum mod encontrado."
        return 1
    fi

    export WORKSHOP_IDS
    log_ok \
    "Mods carregados: ${WORKSHOP_IDS}"
}

mods_pipeline_report()
{
    section \
    "Relatório de Mods"
    mods_report
}

mods_pipeline_backup()
{
    section \
    "Backup de Mods"
    mods_backup_create
}

mods_pipeline_export()
{
    section \
    "Exportação de Mods"
    mods_export_create
}

mods_pipeline_status()
{
    section "Status dos Mods"
    mods_status_show
}

# =============================================================
# INSTALL
# Fluxo:
# prepare
#    |
# download
#    |
# sync
#    |
# keys
#    |
# state
# =============================================================
mods_pipeline_install()
{
    section \
    "Instalação de Mods"
    mods_pipeline_prepare || return 1
    IFS=';' read -ra MOD_LIST <<< "${WORKSHOP_IDS}"
    for item in "${MOD_LIST[@]}"
    do
        local id
        local folder
        id="${item%%:*}"
        folder="${item##*:}"
        log_info \
        "Instalando ${folder}"

        steamcmd_download_item "${id}" \
        || return 1

        mods_sync_one \
            "${id}" \
            "${folder}" \
        || return 1

        local workshop_json
        local updated
        workshop_json="$(steamcmd_workshop_info "${id}")"
        updated="$(steamcmd_workshop_updated "${workshop_json}")"

        if [[ -z "${updated}" ]]
        then
            updated="0"
        fi

        state_set \
            "${id}" \
            "${updated}" \
            "${folder}"
    done

    keys_sync || return 1
    log_ok \
    "Instalação concluída."
}

# =============================================================
# UPDATE
# Responsabilidade:
# updater.sh
# =============================================================
mods_pipeline_update()
{
    section \
    "Atualização de Mods"
    updater_run "$@" || return 1
    mods_validate
}

# =============================================================
# VERIFY
# Apenas valida estrutura
# =============================================================
mods_pipeline_verify()
{
     section \
        "Validação de Mods"
        mods_validate
}

# =============================================================
# ROLLBACK
# =============================================================
mods_pipeline_rollback()
{
    local id="$1"
    if [ -z "${id}" ]
    then
        log_error \
        "Informe WORKSHOP_ID."
        return 1
    fi

    section \
    "Rollback ${id}"

    rollback_restore "${id}" \
    || return 1
    keys_sync
    log_ok \
    "Rollback concluído."
}

# =============================================================
# KEYS
# =============================================================
mods_pipeline_keys()
{
    section \
    "Sincronização de Keys"
    keys_sync
}

# =============================================================
# STATE
# =============================================================
mods_pipeline_state()
{
    section \
    "Estado dos Mods"
    state_list
}

# =============================================================
# STATUS
# =============================================================
mods_pipeline_status()
{
    state_list
}

# =============================================================
# Dispatcher interno
# =============================================================
pipeline_command()
{
case "${1:-}" in
install)
    mods_pipeline_install
;;
update)
    shift
    mods_pipeline_update "$@"
;;
verify)
    mods_pipeline_verify
;;
rollback)
    shift
    mods_pipeline_rollback "$@"
;;
keys)
    mods_pipeline_keys
;;
state)
    mods_pipeline_state
;;
status)
    mods_pipeline_status
;;
*)
    echo
    echo "Uso:"
    echo
    echo " pipeline.sh install"
    echo " pipeline.sh update"
    echo " pipeline.sh verify"
    echo " pipeline.sh rollback ID"
    echo " pipeline.sh keys"
    echo " pipeline.sh state"
    return 1
;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    pipeline_command "$@"
fi
