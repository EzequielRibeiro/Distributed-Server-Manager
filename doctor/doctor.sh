#!/bin/bash
# =============================================================
# doctor/doctor.sh - MÓDULO 05 (DOCTOR)
#
# Agregador do sistema de diagnóstico DSM
#
# Versão: 09.7.3-RC2
# =============================================================

LOG_MODULE="doctor"
DSM_DOCTOR_DIR="${DSM_ROOT}/doctor"
DSM_DOCTOR_REPORT_DIR="${DSM_ROOT}/reports"
RUNTIME_LIB="${DSM_ROOT}/core/lib/runtime.sh"
LOG_LIB="${DSM_ROOT}/core/lib/logger.sh"

if [[ -f "${LOG_LIB}" ]]
then
    source "${LOG_LIB}"
fi

if [[ -f "${RUNTIME_LIB}" ]]
then
    # shellcheck source=/dev/null
    source "${RUNTIME_LIB}"
    runtime_init
fi

# =========================================================
# Dependências Server
# =========================================================

if [[ -f "${DSM_ROOT}/server/status.sh" ]]
then
    source "${DSM_ROOT}/server/status.sh"
fi


if [[ -f "${DSM_ROOT}/server/process.sh" ]]
then
    source "${DSM_ROOT}/server/process.sh"
fi

# =============================================================
# Estado global do Doctor
# =============================================================

declare -ag DOCTOR_REPORT=()
declare -gi DOCTOR_SCORE=0
declare -gi DOCTOR_MAX=0
declare -gi DOCTOR_STATUS=0

# =============================================================
# Relatório Doctor
# =============================================================

DOCTOR_REPORT=()

doctor_report_add()
{
    local name="$1"
    local status="$2"
    local message="$3"

    DOCTOR_REPORT+=(
        "${name}|${status}|${message}"
    )
}

# =============================================================
# Carregamento seguro dos módulos
# =============================================================


doctor_load_module()
{

    local file="$1"

    if [[ -f "${DSM_DOCTOR_DIR}/${file}" ]]
    then
        # shellcheck source=/dev/null
        source "${DSM_DOCTOR_DIR}/${file}"
    else
        log_warn "Arquivo Doctor ausente: ${file}"
    fi

}

# =============================================================
# Módulos Doctor
# =============================================================

doctor_load_module "check_server.sh"
doctor_load_module "check_mods.sh"
doctor_load_module "check_keys.sh"
doctor_load_module "check_disco.sh"
doctor_load_module "check_permissions.sh"
doctor_load_module "diagnose.sh"
doctor_load_module "report.sh"
doctor_load_module "formatter.sh"


# =============================================================
# Integração Mods Metadata
# =============================================================


if [[ -f "${DSM_ROOT}/mods/metadata.sh" ]]
then
    # shellcheck source=/dev/null
    source "${DSM_ROOT}/mods/metadata.sh"

fi



# =============================================================
# Inicialização
# =============================================================


doctor_init()
{

    mkdir -p "${DSM_DOCTOR_REPORT_DIR}"

    DOCTOR_REPORT=()
    DOCTOR_SCORE=0
    DOCTOR_MAX=0
    DOCTOR_STATUS=0

}


# =============================================================
# Executor dos Checks Doctor
# =============================================================

doctor_execute_checks()
{

    if declare -F check_server >/dev/null
    then
        check_server
    fi


    if declare -F check_mods >/dev/null
    then
        check_mods
    fi


    if declare -F check_keys >/dev/null
    then
        check_keys
    fi


    if declare -F check_disco >/dev/null
    then
        check_disco
    fi


    if declare -F check_permissions >/dev/null
    then
        check_permissions
    fi

}


# =============================================================
# Execução principal
# =============================================================

doctor_run()
{

     doctor_init


        # =========================================================
        # Executar módulos Doctor
        # =========================================================

        if declare -F doctor_execute_checks >/dev/null
        then

            doctor_execute_checks

        else

            log_error \
            "Executor Doctor não encontrado."

            return 2

        fi


        local result=0


    if [[ "${DOCTOR_STATUS}" -ne 0 ]]
    then
        result=1
    fi


    # =========================================================
    # Relatório
    # =========================================================

    if declare -F report_save >/dev/null
    then

        local report

        report="$(report_save)"

        [[ -n "${report}" ]] && \
            log_info "Relatório salvo: ${report}"

    fi



    doctor_publish_runtime


    return "${result}"

}

# =============================================================
# JSON Doctor
# =============================================================


doctor_json()
{

cat <<EOF
{
    "score": ${DOCTOR_SCORE},
    "max": ${DOCTOR_MAX},
    "report": [
EOF

    local first=1
    local item

    for item in "${DOCTOR_REPORT[@]}"
    do
        [[ $first -eq 0 ]] && echo ","

        first=0

        IFS='|' read -r label ok detail <<< "${item}"

        jq -n \
            --arg label "${label}" \
            --arg detail "${detail}" \
            --argjson ok "$([[ "${ok}" -eq 0 ]] && echo true || echo false)" \
            '
            {
                label:$label,
                ok:$ok,
                detail:$detail
            }
            '
    done

    echo

    echo "    ]"

    echo "}"

}

doctor_check_result()
{
        local label="$1"
        local status="$2"
        local detail="$3"

        DOCTOR_MAX=$((DOCTOR_MAX + 1))

        if [[ "$status" -eq 0 ]]
        then
            DOCTOR_SCORE=$((DOCTOR_SCORE + 1))
        else
            DOCTOR_STATUS=1
        fi

        doctor_report_add "$label" "$status" "$detail"

}

doctor_ok()
{
    log_info "[Doctor] $1 - $2"
    doctor_check_result "$1" 0 "$2"
}


doctor_warn()
{
    log_warn "[Doctor] $1 - $2"
    doctor_check_result "$1" 1 "$2"
}


doctor_error()
{
    log_error "[Doctor] $1 - $2"
    doctor_check_result "$1" 1 "$2"
}


doctor_publish_runtime()
{

    if ! declare -F runtime_update_resource >/dev/null
    then
        log_warn "Runtime Resource API não disponível."
        return 1
    fi


    local JSON

    JSON="$(doctor_json)"


    if [[ -z "${JSON}" ]]
    then
        log_warn "Doctor JSON vazio."
        return 1
    fi


    runtime_update_resource \
        "$(runtime_host)" \
        "$(runtime_game)" \
        "$(runtime_instance)" \
        "doctor" \
        "${JSON}"


    log_info "Doctor publicado no Runtime."
}

#!/bin/bash
# =============================================================
# core/commands/doctor.sh
#
# CLI Doctor Handler
#
# DSM Module 05
#
# =============================================================


doctor_cli()
{
    source "${DSM_ROOT}/doctor/formatter.sh"
    local ACTION="${1:-status}"


    case "${ACTION}" in


        run)

            "${DSM_ROOT}/doctor/runner.sh"

        ;;


        status)

            if ! declare -F runtime_get >/dev/null
            then
                echo "Runtime indisponível."
                return 1
            fi


            runtime_get doctor

        ;;


        *)

            echo
            echo "Uso:"
            echo
            echo " dsm doctor run"
            echo " dsm doctor status"
            echo

            return 1

        ;;


    esac

}


# =============================================================
# Exportar funções
# =============================================================

export -f doctor_report_add
export -f doctor_load_module
export -f doctor_init
export -f doctor_run
export -f doctor_json
export -f doctor_publish_runtime
export -f doctor_execute_checks
export LOG_CONSOLE=1