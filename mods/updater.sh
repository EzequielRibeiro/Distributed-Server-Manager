#!/bin/bash
# =============================================================
# mods/updater.sh - MÓDULO 03 (MODS)
#
# Atualização dos Mods DayZ
#
# Commit 15
# Universal Mod Event Integration
#
# Responsável por:
# - verificar versões Workshop
# - baixar atualizações
# - criar rollback
# - sincronizar arquivos
# - atualizar estado
# - publicar eventos universais
#
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
# Dependências
# =============================================================

source "${DSM_ROOT}/mods/steamcmd.sh"
source "${DSM_ROOT}/mods/state.sh"
source "${DSM_ROOT}/mods/rollback.sh"
source "${DSM_ROOT}/mods/keys.sh"
source "${DSM_ROOT}/mods/synchronizer.sh"
source "${DSM_ROOT}/mods/detector.sh"


MOD_ENGINE="${DSM_ROOT}/mods/events/mod_engine.sh"


# =============================================================
# Evento Universal de Mods
# =============================================================

mod_event()
{
    local MESSAGE="$1"

    "$MOD_ENGINE" test \
    "$MESSAGE"
}



# =============================================================
# Atualização principal
# =============================================================

updater_run()
{
    local auto_mode="${1:-}"

    section "Verificando atualizações de mods"


    local result=0
    local updated_list=()



    if [ -z "${WORKSHOP_IDS:-}" ]
    then

        WORKSHOP_IDS="$(mods_detect_or_load_workshop_ids || true)"

        if [ -z "${WORKSHOP_IDS}" ]
        then
            log_error \
            "Nenhum Workshop ID encontrado"

            return 1
        fi

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



        log_info \
        "Verificando mod ${folder}"



        local info

        info="$(steamcmd_workshop_info "${id}")"



        if [ "$(echo "${info}" | jq '.response.publishedfiledetails | length')" -eq 0 ]
        then

            log_error \
            "Workshop inválido: ${id}"


            mod_event \
            "@${folder} update failed"


            result=1
            continue

        fi



        local title
        local remote_ts
        local local_ts


        title="$(steamcmd_workshop_title "${info}")"

        remote_ts="$(steamcmd_workshop_updated "${info}")"

        local_ts="$(state_get_timestamp "${id}")"



        if [ -z "${local_ts}" ]
        then

            log_warn \
            "${folder} sem estado"


            continue

        fi



        if [ "${remote_ts}" = "${local_ts}" ]
        then

            printf "%-35s ... Atualizado\n" "${title}"

            continue

        fi



        printf "%-35s ... Nova versão\n" "${title}"



        #
        # Snapshot
        #

        current_folder="$(state_get_folder "${id}")"


        if ! rollback_snapshot \
            "${id}" \
            "${current_folder}"
        then

            log_warn \
            "Falha rollback: ${folder}"

        fi



        #
        # Download
        #

        if ! steamcmd_download_item "${id}"
        then

            log_error \
            "Falha download: ${folder}"


            mod_event \
            "@${folder} update failed"


            rollback_restore "${id}"

            result=1

            continue

        fi



        #
        # Sincronização
        #

        if ! mods_sync_once \
            "${id}" \
            "${folder}"
        then

            log_error \
            "Falha sincronização: ${folder}"


            mod_event \
            "@${folder} update failed"


            rollback_restore "${id}"

            result=1

            continue

        fi



        #
        # Atualizar estado
        #

        state_set \
            "${id}" \
            "${remote_ts}" \
            "${folder}"



        updated_list+=("${title}")



        #
        # Evento Universal
        #

        mod_event \
        "@${folder} updated"



    done



    #
    # Keys após atualização
    #

    keys_sync



    if [ "${#updated_list[@]}" -gt 0 ]
    then

        log_ok \
        "Mods atualizados: ${updated_list[*]}"


        notify_dispatch \
        "mods_updated" \
        "{\"mods\":\"${updated_list[*]}\"}"



        if [ "${auto_mode}" = "--auto" ] &&
           server_pid >/dev/null 2>&1
        then

            restart_run

        fi


    else

        log_info \
        "Nenhuma atualização encontrada"

    fi


    return "${result}"

}



# =============================================================
# Rollback manual
# =============================================================

updater_rollback()
{

    local id="$1"


    if [ -z "${id}" ]
    then

        log_error \
        "Uso: dsm mods rollback ID"

        return 1

    fi



    rollback_restore "${id}" || return 1


    keys_sync



    mod_event \
    "@${id} rollback"



    log_ok \
    "Rollback concluído"

}



# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    updater_run "$@"

fi