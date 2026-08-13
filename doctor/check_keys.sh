#!/bin/bash
# =============================================================
# doctor/check_keys.sh - MÓDULO 05 (DOCTOR)
#
# Verificação das Keys DayZ
#
# Responsável por:
#
# - keys globais do servidor
# - keys opcionais dos mods
#
# Fonte:
#
#   config/dsm.conf
#
# =============================================================


LOG_MODULE="doctor"



check_keys()
{

    local failures=0


    local keys_dir
    keys_dir="${SERVERFILES_PATH}/keys"


    local mods_dir
    mods_dir="${SERVERFILES_PATH}/mods"



    # =========================================================
    # Keys globais
    # =========================================================


    if [[ -d "${keys_dir}" ]]
    then


        local global_keys


        global_keys=$(find "${keys_dir}" \
            -type f \
            -name "*.bikey" \
            2>/dev/null |
            wc -l)



        if [[ "${global_keys}" -gt 0 ]]
        then

            doctor_ok \
            "Keys" \
            "${global_keys} key(s) encontrada(s)"


        else

            doctor_error \
            "Keys" \
            "Nenhuma .bikey encontrada"

            ((failures++))

        fi


    else


        doctor_error \
        "Keys" \
        "Diretório ausente: ${keys_dir}"

        ((failures++))


    fi



    # =========================================================
    # Mods
    # =========================================================


    if [[ -d "${mods_dir}" ]]
    then


        local total=0
        local with_keys=0



        while IFS= read -r mod
        do

            ((total++))


            if [[ -d "${mod}/Keys" ]] ||
               [[ -d "${mod}/keys" ]]
            then

                ((with_keys++))

            fi


        done < <(
            find "${mods_dir}" \
            -maxdepth 1 \
            -type d \
            -name "@*" \
            2>/dev/null
        )



        if [[ "${with_keys}" -gt 0 ]]
                then

                    doctor_ok \
                    "Mod Keys" \
                    "${with_keys} mod(s) possuem assinatura Keys"

                else

                    doctor_ok \
                    "Mod Keys" \
                    "Nenhum mod com assinatura Keys obrigatória"

                fi



    fi



    (( failures > 0 )) && return 1

    return 0

}