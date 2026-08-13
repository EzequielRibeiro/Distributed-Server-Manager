#!/bin/bash
# =============================================================
# doctor/check_disco.sh - MÓDULO 05 (DOCTOR)
#
# Validação:
#
# - espaço livre do servidor
# - usa mesma regra do monitor
#
# =============================================================


LOG_MODULE="doctor"

# =========================================================
# Dependência Monitor Resources
# =========================================================

RESOURCE_LIB="${DSM_ROOT}/monitor/resources.sh"


if [[ -f "${RESOURCE_LIB}" ]]
then
    # shellcheck source=/dev/null
    source "${RESOURCE_LIB}"
else
    log_error "Biblioteca de recursos não encontrada: ${RESOURCE_LIB}"
fi

check_disco()
{


    local free_pct

    local free_human



    free_pct="$(resources_disk_free_pct)"

    free_human="$(resources_disk_free_human)"



    local limit

    limit="${HEALTH_DISK_WARN_PCT:-15}"


    # =========================================================
    # Falha na leitura
    # =========================================================


    if [ -z "$free_pct" ]
    then

        doctor_error \
        "Espaço em Disco" \
        "não foi possível verificar disco"

        return 1


    fi







    # =========================================================
    # Espaço suficiente
    # =========================================================


    if [ "$free_pct" -ge "$limit" ]
    then


        doctor_ok \
        "Espaço em Disco" \
        "$free_human livres ($free_pct%)"


        return 0


    else


        doctor_error \
        "Espaço em Disco" \
        "$free_human livres ($free_pct%) - abaixo do limite ${limit}%"


        return 1



    fi


}
