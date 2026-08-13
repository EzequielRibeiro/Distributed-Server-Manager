#!/usr/bin/env bash
# =============================================================
# doctor/check_server.sh - MÓDULO 05 (DOCTOR)
#
# Diagnóstico do servidor DayZ
# =============================================================

LOG_MODULE="doctor"

check_server()
{
    local failures=0

    # =========================================================
    # Validação de configuração
    # =========================================================

    if [[ -z "${LINUXGSM_PATH:-}" ]]
    then
        doctor_error \
            "LinuxGSM" \
            "LINUXGSM_PATH não definido"
            failures=$((failures + 1))
        return 1
    fi

    if [[ -z "${SERVERFILES_PATH:-}" ]]
    then
        doctor_error \
            "Serverfiles" \
            "SERVERFILES_PATH não definido"
             failures=$((failures + 1))
        return 1
    fi

    # =========================================================
    # LinuxGSM
    # =========================================================

    local LGSM_BIN

    LGSM_BIN="${LINUXGSM_PATH}/${INSTANCE_NAME}"

    if [[ -x "${LGSM_BIN}" ]]
    then
        doctor_ok \
            "LinuxGSM" \
            "Executável encontrado: ${LGSM_BIN}"
    else
        doctor_error \
            "LinuxGSM" \
            "Executável não encontrado: ${LGSM_BIN}"

        failures=$((failures + 1))
    fi

    # =========================================================
    # Serverfiles
    # =========================================================

    if [[ -d "${SERVERFILES_PATH}" ]]
    then
        doctor_ok \
            "Serverfiles" \
            "Diretório encontrado: ${SERVERFILES_PATH}"
    else
        doctor_error \
            "Serverfiles" \
            "Diretório ausente: ${SERVERFILES_PATH}"
            failures=$((failures + 1))
    fi

    # =========================================================
    # Configuração DayZ
    # =========================================================

    if [[ -f "${SERVERFILES_PATH}/cfg/dayzserver.server.cfg" ]]
    then
        doctor_ok \
            "Configuração DayZ" \
            "Arquivo encontrado: cfg/dayzserver.server.cfg"

    elif [[ -f "${SERVERFILES_PATH}/serverDZ.cfg" ]]
    then
        doctor_ok \
            "Configuração DayZ" \
            "Arquivo encontrado: serverDZ.cfg"

    else
        doctor_error \
            "Configuração DayZ" \
            "Arquivo de configuração não encontrado"
             failures=$((failures + 1))
    fi

    # =========================================================
    # Processo DayZ
    # =========================================================

    local STATUS
    local PID

    STATUS="$(server_status)"

    case "${STATUS}" in

        ONLINE)

            PID="$(server_pid)"

            doctor_ok \
                "Processo DayZ" \
                "Servidor em execução (PID ${PID})"

        ;;

        OFFLINE)

            doctor_error \
                "Processo DayZ" \
                "Servidor não está em execução"

            failures=$((failures + 1))

        ;;

        "PROCESSO INVÁLIDO")

            PID="$(server_pid)"

            doctor_error \
                "Processo DayZ" \
                "PID ${PID} não pertence ao DayZServer"

            failures=$((failures + 1))

        ;;

        *)

            doctor_error \
                "Processo DayZ" \
                "Estado desconhecido: ${STATUS}"

            failures=$((failures + 1))

        ;;

    esac

    if [[ "${failures}" -eq 0 ]]
    then
        return 0
    else
        return 1
    fi
}