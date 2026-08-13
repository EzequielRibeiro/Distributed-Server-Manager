#!/bin/bash
# =============================================================
# mods/validator.sh - MÓDULO 03 (MODS)
#
# Validação dos Mods DayZ
#
# Commit 15
# Universal Mod Event Integration
#
# Responsável por:
# - validar estrutura de mods
# - validar meta.cpp
# - validar Workshop ID
# - validar keys
# - validar integridade básica
#
# NÃO FAZ:
# - SteamCMD
# - instalação
# - atualização
# - rollback
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

source "${DSM_ROOT}/mods/state.sh"
source "${DSM_ROOT}/mods/detector.sh"
source "${DSM_ROOT}/core/events.sh"

# =============================================================
# Diretórios
# =============================================================

MODS_DIR="${SERVERFILES_PATH}/mods"
KEYS_DIR="${SERVERFILES_PATH}/keys"


# =============================================================
# Evento Universal Mods
# =============================================================

mod_event()
{
    local TYPE="$1"
    local MESSAGE="$2"

    event_info \
    "$TYPE" \
    mod \
    "$MESSAGE" \
    DSM \
    "${DSM_SERVER:-server01}" \
    "${DSM_GAME:-dayz}" \
    "${DSM_INSTANCE:-survival01}"
}



# =============================================================
# Validar diretório principal
# =============================================================

mods_validate_directory()
{

    if [ ! -d "${MODS_DIR}" ]
    then

        log_error \
        "Diretório de Mods não encontrado: ${MODS_DIR}"

        return 1

    fi


    return 0

}



# =============================================================
# Validar mod individual
#
# Uso:
# mods_validate_one ID @MOD
#
# =============================================================

mods_validate_one()
{

    local id="$1"
    local folder="$2"

    local path="${MODS_DIR}/${folder}"



    #
    # Pasta ou link simbólico
    #

  if [ ! -e "${path}" ]
  then

      log_error \
      "Diretório de mod não encontrado ou link inválido: ${folder}"


      mod_event \
      MOD_MISSING \
      "${folder}: diretório não encontrado ou link inválido"


      return 1

  fi

    #
    # Resolver link simbólico
    #

    if [ -L "${path}" ]
    then

        REAL_PATH=$(readlink -f "${path}" || true)


        if [ -z "${REAL_PATH}" ] || [ ! -d "${REAL_PATH}" ]
        then

            log_error \
            "Diretório de mod não encontrado ou link inválido: ${folder}"


            mod_event \
            MOD_PATH_INVALID \
            "${folder}: diretório ausente ou link quebrado"


            return 1

        fi


        path="${REAL_PATH}"

    fi



    #
    # Garantir que é diretório
    #

    if [ ! -d "${path}" ]
    then

        log_error \
        "Caminho do mod não é um diretório válido: ${folder}"


        mod_event \
        MOD_PATH_INVALID \
        "${folder}: caminho inválido"


        return 1

    fi



    #
    # meta.cpp
    #

    local meta="${path}/meta.cpp"


    if [ ! -f "${meta}" ]
    then

        log_error \
        "${folder}: meta.cpp não encontrado"


        mod_event \
        MOD_INVALID_META \
        "${folder}: meta.cpp ausente"


        return 1

    fi



    #
    # Workshop ID
    #

    if ! grep -q \
    "publishedid *= *${id}" \
    "${meta}"
    then

        log_error \
        "${folder}: Workshop ID inválido"



        mod_event \
        MOD_INVALID_META \
        "${folder}: Workshop ID inválido"


        return 1

    fi



    #
    # Sucesso
    #

    log_ok \
    "${folder} validado"


    return 0

}


# =============================================================
# Validar todos os mods
# =============================================================

mods_validate()
{

    section \
    "Validando Mods"



    local fail=0



    mods_validate_directory \
    || return 1



    if [ -z "${WORKSHOP_IDS:-}" ]
    then

        WORKSHOP_IDS="$(mods_detect_or_load_workshop_ids || true)"

    fi



    if [ -z "${WORKSHOP_IDS:-}" ]
    then

        log_error \
        "Nenhum mod configurado"

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



        mods_validate_one \
        "${id}" \
        "${folder}" \
        || fail=1


    done



    #
    # Keys
    #

    mods_validate_keys \
    || fail=1



    if [ "${fail}" -eq 0 ]
    then

        log_ok \
        "Todos os Mods estão válidos"

    else

        log_error \
        "Falha na validação dos Mods"

    fi



    return "${fail}"

}



# =============================================================
# Validar Keys
# =============================================================

mods_validate_keys()
{


    if [ ! -d "${KEYS_DIR}" ]
    then

        mod_event \
        KEY_MISSING \
        "Keys directory missing"

        return 1

    fi



    local count


    count=$(find "${KEYS_DIR}" \
        -type f \
        -name "*.bikey" \
        | wc -l)



    if [ "${count}" -eq 0 ]
    then

        log_warn \
        "Nenhuma key .bikey encontrada"



        mod_event \
        "@mods missing key"


        return 1

    fi

   log_ok \
   "Keys encontradas: ${count}"


   event_success \
   KEYS_SYNCED \
   mod \
   "Keys encontradas: ${count}" \
   DSM \
   "${DSM_SERVER:-server01}" \
   "${DSM_GAME:-dayz}" \
   "${DSM_INSTANCE:-survival01}"


    return 0

}



# =============================================================
# Validar permissões
# =============================================================

mods_validate_permissions()
{

    local fail=0


    if [ ! -r "${MODS_DIR}" ]
    then

        log_error \
        "Sem permissão de leitura em ${MODS_DIR}"


        fail=1

    fi


    return "${fail}"

}



# =============================================================
# Dispatcher
# =============================================================

validator_command()
{

case "${1:-}" in


all)

    mods_validate

;;


mod)

    mods_validate_one \
    "$2" \
    "$3"

;;


keys)

    mods_validate_keys

;;


permissions)

    mods_validate_permissions

;;


*)

    echo
    echo "Uso:"
    echo
    echo " validator.sh all"
    echo " validator.sh mod ID @MOD"
    echo " validator.sh keys"
    echo " validator.sh permissions"

    return 1

;;

esac

}



# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    validator_command "$@"

fi