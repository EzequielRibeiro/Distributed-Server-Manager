#!/bin/bash

# =============================================================
# DSM Provider - LinuxGSM
#
# Responsável por executar servidores via LinuxGSM
# =============================================================


provider_lgsm_bin()
{

    if [[ -z "${LINUXGSM_PATH:-}" ]]
    then
        echo "LINUXGSM_PATH não definido."
        return 1
    fi


    if [[ -z "${INSTANCE_NAME:-}" ]]
    then
        echo "INSTANCE_NAME não definido."
        return 1
    fi


    local BIN="${LINUXGSM_PATH}/${INSTANCE_NAME}"


    if [[ ! -x "${BIN}" ]]
    then
        echo "LinuxGSM não encontrado:"
        echo "${BIN}"
        return 1
    fi


    echo "${BIN}"

}



provider_start()
{

    local LGSM_BIN


    LGSM_BIN="$(provider_lgsm_bin)" || return 1


    echo
    echo "LinuxGSM:"
    echo "${LGSM_BIN}"
    echo


    cd "${LINUXGSM_PATH}" || return 1


    "${LGSM_BIN}" start

}



provider_stop()
{

    local LGSM_BIN


    LGSM_BIN="$(provider_lgsm_bin)" || return 1


    cd "${LINUXGSM_PATH}" || return 1


    "${LGSM_BIN}" stop

}



provider_restart()
{

    local LGSM_BIN


    LGSM_BIN="$(provider_lgsm_bin)" || return 1


    cd "${LINUXGSM_PATH}" || return 1


    "${LGSM_BIN}" restart

}