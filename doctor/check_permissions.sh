#!/bin/bash
# =============================================================
# doctor/check_permissions.sh - MÓDULO 05 (DOCTOR)
#
# Diagnóstico de permissões do servidor DayZ
#
# Fonte única:
#
#   /opt/dsm/config/dsm.conf
#
# Não utiliza:
#
#   settings.conf
#   LGSM_DIR
#
# Verifica:
#
# - existência do Serverfiles
# - proprietário
# - leitura
# - escrita
# - execução
#
# =============================================================


LOG_MODULE="doctor"



# =============================================================
# Carregar configuração DSM
# =============================================================


if [ -z "${DSM_ROOT:-}" ]
then

    echo "DSM_ROOT não definido." >&2

    return 1 2>/dev/null || exit 1

fi



DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"



if [ ! -r "${DSM_CONFIG}" ]
then

    echo "Configuração não encontrada:"
    echo "${DSM_CONFIG}"

    return 1 2>/dev/null || exit 1

fi



# shellcheck source=/dev/null
source "${DSM_CONFIG}"



# =============================================================
# Validação de contexto
#
# IMPORTANTE:
# Este arquivo pode ser carregado via source sem que exista
# uma instância selecionada. Portanto, nenhuma validação de
# SERVERFILES_PATH/DSM_USER deve ocorrer durante o carregamento.
# A validação é feita dentro de check_permissions().
# =============================================================


# =============================================================
# Verificar permissões
# =============================================================


check_permissions()
{

    #
    # Validação lazy: somente quando o check for executado.
    #
    if [ -z "${SERVERFILES_PATH:-}" ]
    then
        if declare -F doctor_error >/dev/null
        then
            doctor_error \
                "Permissões" \
                "SERVERFILES_PATH não definido para esta instância"
        else
            echo \
                "SERVERFILES_PATH não definido para esta instância" \
                >&2
        fi

        return 1
    fi

    if [ -z "${DSM_USER:-}" ]
    then
        if declare -F doctor_error >/dev/null
        then
            doctor_error \
                "Permissões" \
                "DSM_USER não definido"
        else
            echo "DSM_USER não definido" >&2
        fi

        return 1
    fi


    local ok=0

    local target="${SERVERFILES_PATH}"



    # ---------------------------------------------------------
    # Existência
    # ---------------------------------------------------------


    if [ ! -d "${target}" ]
    then


        doctor_error \
        "Permissões" \
        "diretório ausente: ${target}"
        return 1


    fi



    # ---------------------------------------------------------
    # Proprietário
    # ---------------------------------------------------------


    local owner


    owner=$(stat -c "%U" "${target}" 2>/dev/null)



    if [ "${owner}" = "${DSM_USER}" ]
    then


        doctor_ok \
        "Owner" \
        "diretório pertence a ${owner}"

    else

        doctor_error \
        "Owner" \
        "proprietário ${owner}, esperado ${DSM_USER}"

        ok=1


    fi

    # ---------------------------------------------------------
    # Leitura
    # ---------------------------------------------------------

    if sudo -u "${DSM_USER}" test -r "${target}"
    then

        doctor_ok \
        "Permissão Leitura" \
        "usuário DSM consegue ler"

    else

        doctor_error \
        "Permissão Leitura" \
        "usuário ${DSM_USER} sem permissão de leitura"

        ok=1

    fi


    # ---------------------------------------------------------
    # Escrita
    # ---------------------------------------------------------

    if sudo -u "${DSM_USER}" test -w "${target}"
    then

        doctor_ok \
        "Permissão Escrita" \
        "usuário DSM consegue escrever"

    else

        doctor_error \
        "Permissão Escrita" \
        "usuário ${DSM_USER} sem permissão de escrita"

        ok=1

    fi


    # ---------------------------------------------------------
    # Execução
    # ---------------------------------------------------------

    if sudo -u "${DSM_USER}" test -x "${target}"
    then

        doctor_ok \
        "Permissão Execução" \
        "diretório acessível"

    else

        doctor_error \
        "Permissão Execução" \
        "usuário ${DSM_USER} sem permissão de execução"

        ok=1

    fi

    return ${ok}

}



# =============================================================
# Execução direta
# =============================================================


if [ "${BASH_SOURCE[0]}" = "$0" ]
then

    check_permissions

    exit $?

fi