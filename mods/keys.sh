#!/bin/bash
# =============================================================
# mods/keys.sh - MÓDULO 03 (MODS)
#
# Gerenciamento das Keys dos Mods DayZ
#
# Responsável:
# - localizar keys dos mods
# - copiar .bikey para servidor
# - limpar keys antigas
# - validar keys instaladas
# - emitir eventos DSM
#
# Eventos:
#
# KEY_MISSING
# MOD_KEY_SYNCED
# KEY_SYNC_FAILED
#
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
# Dependências
# =============================================================

MOD_ENGINE="${DSM_ROOT}/mods/events/mod_engine.sh"


# =============================================================
# Configuração
# =============================================================

MODS_DIR="${SERVERFILES_PATH}/mods"
KEYS_DIR="${SERVERFILES_PATH}/keys"


mkdir -p "${KEYS_DIR}"



# =============================================================
# Localizar Mod pelo Workshop ID
# =============================================================

keys_find_mod_path()
{
    local mod_id="$1"


    [ -z "${mod_id}" ] && return 1



    while IFS= read -r meta
    do

        if grep -q \
        "publishedid[[:space:]]*=[[:space:]]*${mod_id}" \
        "${meta}"
        then

            dirname "${meta}"
            return 0

        fi


    done < <(
        find -L \
        "${MODS_DIR}" \
        -name meta.cpp \
        2>/dev/null
    )


    return 1
}



# =============================================================
# Localizar .bikey
# =============================================================

keys_find_files()
{
    local mod_path="$1"


    [ ! -d "${mod_path}" ] && return 1


    find -L \
        "${mod_path}" \
        -type f \
        -iname "*.bikey" \
        2>/dev/null
}



# =============================================================
# Evento auxiliar
# =============================================================

keys_event()
{
    local message="$1"


    if [ -x "${MOD_ENGINE}" ]
    then

        "${MOD_ENGINE}" test "${message}"

    fi
}



# =============================================================
# Sincronizar keys de um mod
# =============================================================

keys_sync_mod()
{
    local mod_id="$1"


    local mod_path

    mod_path="$(keys_find_mod_path "${mod_id}")"



    if [ -z "${mod_path}" ]
    then

        log_warn \
        "Mod não encontrado para keys: ${mod_id}"


        keys_event \
        "@${mod_id} missing"


        return 1

    fi



    local count=0



    while IFS= read -r key
    do

        [ -z "${key}" ] && continue


        cp -f \
            "${key}" \
            "${KEYS_DIR}/"


        count=$((count+1))


    done < <(
        keys_find_files "${mod_path}"
    )



    if [ "${count}" -eq 0 ]
    then

        log_warn \
        "Nenhuma key encontrada: ${mod_id}"


        keys_event \
        "@${mod_id} missing key"


        return 1

    fi



    log_ok \
    "Keys sincronizadas: ${mod_id} (${count})"



    keys_event \
    "@${mod_id} keys synchronized"



    return 0
}



# =============================================================
# Sincronizar todas as keys
# =============================================================

keys_sync()
{

    local ids="${WORKSHOP_IDS:-}"


    if [ -z "${ids}" ]
    then

        log_warn \
        "WORKSHOP_IDS vazio para sincronização de keys"


        return 1

    fi



    local item
    local id


    IFS=';' read -ra MOD_LIST <<< "${ids}"



    local failed=0



    for item in "${MOD_LIST[@]}"
    do

        id="${item%%:*}"

        id="$(echo "${id}" | xargs)"


        [ -z "${id}" ] && continue



        keys_sync_mod "${id}" \
        || failed=1


    done



    if [ "${failed}" -eq 0 ]
    then

        keys_event \
        "MOD keys synchronized"

    else

        keys_event \
        "MOD keys synchronization failed"

    fi



    return "${failed}"
}



# =============================================================
# Limpar keys antigas
# =============================================================

keys_cleanup()
{

    if [ ! -d "${KEYS_DIR}" ]
    then
        return 0
    fi



    find "${KEYS_DIR}" \
        -type f \
        -name "*.bikey" \
        -delete



    log_ok \
    "Keys antigas removidas"

}



# =============================================================
# Status
# =============================================================

keys_status()
{

    local total


    total=$(find "${KEYS_DIR}" \
        -type f \
        -name "*.bikey" \
        2>/dev/null | wc -l)



    echo "Keys instaladas: ${total}"

}



# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

case "${1:-}" in


sync)

    keys_sync

;;


cleanup)

    keys_cleanup

;;


status)

    keys_status

;;


*)

echo "
Uso:

 keys.sh sync

 keys.sh cleanup

 keys.sh status
"

;;


esac

fi