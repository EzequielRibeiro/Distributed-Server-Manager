#!/bin/bash
# =============================================================
# doctor/check_mods.sh
#
# Diagnóstico dos Mods DayZ
#
# Runtime compatible
#
# =============================================================


LOG_MODULE="doctor"



check_mods()
{

    local failures=0


    local mods_dir

    mods_dir="${SERVERFILES_PATH}/mods"



    if [[ ! -d "${mods_dir}" ]]
    then

        doctor_error \
        "Mods" \
        "Diretório ausente: ${mods_dir}"

        return 1

    fi



    local count


    count="$(
        find -L "${mods_dir}" \
        -mindepth 1 \
        -maxdepth 1 \
        \( -type d -o -type l \) \
        -name "@*" \
        2>/dev/null |
        wc -l
    )"



    if (( count == 0 ))
    then

        doctor_error \
        "Mods" \
        "Nenhum mod encontrado"

        return 1

    fi



    doctor_ok \
    "Mods" \
    "${count} mod(s) instalado(s)"



    local empty=0


    while IFS= read -r mod
    do

        if [[ -z "$(find -L "${mod}" -mindepth 1 -print -quit 2>/dev/null)" ]]
        then

            ((empty++))

        fi


    done < <(
        find -L "${mods_dir}" \
        -mindepth 1 \
        -maxdepth 1 \
        \( -type d -o -type l \) \
        -name "@*"
    )



    if (( empty > 0 ))
    then

        doctor_error \
        "Mods Vazios" \
        "${empty} mod(s) sem arquivos"

        ((failures++))

    else

        doctor_ok \
        "Mods Vazios" \
        "Todos os mods possuem arquivos"

    fi



    doctor_check_mods_metadata



    (( failures > 0 )) && return 1

    return 0

}






doctor_check_mods_metadata()
{


    local mods_count

    local meta_count



    mods_count="$(
        find -L "${SERVERFILES_PATH}/mods" \
        -mindepth 1 \
        -maxdepth 1 \
        -name "@*" \
        2>/dev/null |
        wc -l
    )"



    meta_count="$(
        find -L "${SERVERFILES_PATH}/mods" \
        -mindepth 2 \
        -maxdepth 2 \
        -name "meta.cpp" \
        2>/dev/null |
        wc -l
    )"



    doctor_ok \
    "Metadata Mods" \
    "${mods_count} mods encontrados"



    if (( meta_count == mods_count ))
    then

        doctor_ok \
        "Meta CPP" \
        "${meta_count}/${mods_count} meta.cpp encontrados"

    else

        doctor_warn \
        "Meta CPP" \
        "${meta_count}/${mods_count} meta.cpp encontrados"

    fi



    if declare -F mods_scan_metadata >/dev/null
    then

        mods_scan_metadata >/dev/null 2>&1


        doctor_ok \
        "Workshop IDs" \
        "Scanner executado"

    else

        doctor_warn \
        "Workshop IDs" \
        "Scanner indisponível"

    fi



    if [[ -n "${WORKSHOP_IDS:-}" ]]
    then

        doctor_ok \
        "WORKSHOP_IDS" \
        "Configurado"

    else

        doctor_warn \
        "WORKSHOP_IDS" \
        "Não configurado"

    fi


}