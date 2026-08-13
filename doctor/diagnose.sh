#!/bin/bash
# =============================================================
# monitor/diagnose.sh - MÓDULO 04 (MONITOR)
#
# DSM - DayZ Server Manager
#
# Versão: 09.7.3-RC2
#
# Diagnóstico completo do servidor DayZ.
#
# Responsável por verificar:
#
#   • LinuxGSM
#   • Configuração LinuxGSM
#   • Serverfiles
#   • Configuração DayZ
#   • Processo DayZ
#   • Mods
#   • Recursos do sistema
#
# Utilizado por:
#
#   dsm monitor
#   dsm doctor
#
# =============================================================


export LOG_MODULE="monitor"
# =============================================================
# Ambiente DSM
# =============================================================

if [[ -z "${DSM_ROOT:-}" ]]
then
    export DSM_ROOT="/opt/dsm"
fi


# =============================================================
# Bootstrap DSM
# =============================================================

BOOTSTRAP="${DSM_ROOT}/core/bootstrap.sh"


if [[ ! -f "${BOOTSTRAP}" ]]
then

    echo "Bootstrap não encontrado:"
    echo "${BOOTSTRAP}"

    return 1 2>/dev/null || exit 1

fi


if ! declare -F log_info >/dev/null
then
    source "${DSM_ROOT}/core/bootstrap.sh"
fi


source "${DSM_ROOT}/core/lib/runtime.sh"
source "${DSM_ROOT}/core/lib/json.sh"
source "${DSM_ROOT}/core/lib/runtime_metrics.sh"

runtime_init


# =============================================================
# Configuração DSM
# =============================================================

DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"


if [[ ! -f "${DSM_CONFIG}" ]]
then

    log_error "Arquivo de configuração não encontrado:"
    echo "${DSM_CONFIG}"

    return 1 2>/dev/null || exit 1

fi


# shellcheck source=/dev/null
source "${DSM_CONFIG}"



# =============================================================
# Variáveis globais de diagnóstico
# =============================================================


STATE_DIR="${DSM_ROOT}/dashboard/state"

SERVER_STATE="${STATE_DIR}/server_state.json"

METRICS_STATE="${STATE_DIR}/metrics_state.json"

EVENTS_STATE="${STATE_DIR}/events_state.json"

MONITOR_STATUS=0


# LinuxGSM

STATUS_LGSM="unknown"

STATUS_LGSM_CONFIG="unknown"

LGSM_CONFIG_PATH=""

LGSM_COMMON_CFG=""

LGSM_INSTANCE_CFG=""

LGSM_IP=""

LGSM_PORT=""

LGSM_APPID=""

LGSM_BEPATH=""

LGSM_MODS=""


# Processo

PROCESS_PID=""

PROCESS_CPU=""

PROCESS_RAM=""


# Mods

MOD_COUNT=0


# Recursos

RESOURCE_CPU=""

RESOURCE_MEM=""

RESOURCE_DISK=""

metrics_value()
{
    local PATH_KEY="$1"

    python3 - "$METRICS_STATE" "$PATH_KEY" <<'PY'
import json
import sys

file=sys.argv[1]
key=sys.argv[2]

try:
    with open(file) as f:
        data=json.load(f)

    value=data

    for part in key.split("."):
        value=value.get(part, "-")

    print(value)

except Exception as e:
    print("-", file=sys.stderr)
PY
}


# =============================================================
# Helpers
# =============================================================


print_title()
{

    echo
    echo "============================================================"
    echo " $1"
    echo "============================================================"

}



print_ok()
{

    printf "[OK] %s\n" "$1"

}



print_fail()
{

    printf "[FALHA] %s\n" "$1"

}



print_warn()
{

    printf "[WARN] %s\n" "$1"

}



set_failure()
{

    MONITOR_STATUS=1

}

# =============================================================
# Diagnóstico LinuxGSM
# =============================================================

diagnose_lgsm()
{

    print_title "LinuxGSM"


    STATUS_LGSM="failed"


    #
    # Validar caminho LinuxGSM
    #
    if [[ -z "${LINUXGSM_PATH:-}" ]]
    then

        print_fail "LINUXGSM_PATH não definido."

        set_failure

        return 1

    fi



    if [[ ! -d "${LINUXGSM_PATH}" ]]
    then

        print_fail "Diretório LinuxGSM não encontrado."

        echo "Local..........: ${LINUXGSM_PATH}"

        set_failure

        return 1

    fi



    #
    # Validar serverfiles
    #
    if [[ ! -d "${LINUXGSM_PATH}/serverfiles" ]]
    then

        print_fail "Serverfiles não encontrado."

        set_failure

        return 1

    fi



    #
    # Detectar instância LinuxGSM
    #
    local detected_instance=""



    #
    # 1 - Usar INSTANCE_NAME configurado
    #
    if [[ -n "${INSTANCE_NAME:-}" ]]
    then

        if [[ -x "${LINUXGSM_PATH}/${INSTANCE_NAME}" ]]
        then

            detected_instance="${INSTANCE_NAME}"

        fi

    fi



    #
    # 2 - Detectar pelo config-lgsm
    #
    if [[ -z "${detected_instance}" ]]
    then

        if [[ -d "${LINUXGSM_PATH}/lgsm/config-lgsm" ]]
        then


            detected_instance="$(
                find "${LINUXGSM_PATH}/lgsm/config-lgsm" \
                -mindepth 1 \
                -maxdepth 1 \
                -type d \
                -printf '%f\n' \
                | head -n 1
            )"


        fi

    fi



    #
    # 3 - Detectar executável
    #
    if [[ -z "${detected_instance}" ]]
    then


        while IFS= read -r file
        do

            base="$(basename "${file}")"


            case "${base}" in

                steamcmd.sh|linuxgsm.sh|install.sh|update.sh)
                    continue
                    ;;

            esac


            detected_instance="${base}"

            break


        done < <(

            find "${LINUXGSM_PATH}" \
            -maxdepth 1 \
            -type f \
            -perm -111

        )


    fi



    #
    # Nenhuma instância encontrada
    #
    if [[ -z "${detected_instance}" ]]
    then

        print_fail "Instância LinuxGSM não encontrada."

        set_failure

        return 1

    fi



    #
    # Definir instância
    #
    INSTANCE_NAME="${detected_instance}"


    GSM_BIN="${LINUXGSM_PATH}/${INSTANCE_NAME}"



    #
    # Validar executável
    #
    if [[ ! -x "${GSM_BIN}" ]]
    then

        print_fail "Executável LinuxGSM inválido."

        echo "Executável.....: ${GSM_BIN}"

        set_failure

        return 1

    fi



    print_ok "LinuxGSM encontrado."


    echo

    echo "Instância......: ${INSTANCE_NAME}"

    echo "Executável.....: ${GSM_BIN}"

    echo "Serverfiles....: ${LINUXGSM_PATH}/serverfiles"



    #
    # Validar resposta LinuxGSM
    #
    if timeout 10 "${GSM_BIN}" details >/dev/null 2>&1
    then

        print_ok "LinuxGSM respondeu corretamente."

    else

        print_warn "Não foi possível validar comando details."

    fi



    STATUS_LGSM="ok"


    return 0

}

# =============================================================
# Diagnóstico Configuração LinuxGSM
# =============================================================

diagnose_lgsm_config()
{

    print_title "Configuração LinuxGSM"


    STATUS_LGSM_CONFIG="failed"



    #
    # Validar instância
    #
    if [[ -z "${INSTANCE_NAME:-}" ]]
    then

        print_fail "INSTANCE_NAME não definido."

        set_failure

        return 1

    fi



    #
    # Diretório config-lgsm
    #
    LGSM_CONFIG_PATH="${LINUXGSM_PATH}/lgsm/config-lgsm/${INSTANCE_NAME}"



    if [[ ! -d "${LGSM_CONFIG_PATH}" ]]
    then

        print_fail "Diretório config-lgsm não encontrado."

        echo "Local..........: ${LGSM_CONFIG_PATH}"

        set_failure

        return 1

    fi



    print_ok "Diretório config-lgsm encontrado."

    echo

    echo "Local..........: ${LGSM_CONFIG_PATH}"



    #
    # common.cfg
    #
    LGSM_COMMON_CFG="${LGSM_CONFIG_PATH}/common.cfg"


    if [[ ! -f "${LGSM_COMMON_CFG}" ]]
    then

        print_fail "common.cfg não encontrado."

        set_failure

        return 1

    fi


    print_ok "common.cfg encontrado."



    #
    # Configuração específica
    #
    LGSM_INSTANCE_CFG="${LGSM_CONFIG_PATH}/${INSTANCE_NAME}.cfg"



    if [[ -f "${LGSM_INSTANCE_CFG}" ]]
    then

        print_ok "${INSTANCE_NAME}.cfg encontrado."

    else

        print_warn "${INSTANCE_NAME}.cfg não encontrado."

    fi



    #
    # Ler parâmetros básicos
    #

    LGSM_IP="$(
        grep -E '^ip=' "${LGSM_COMMON_CFG}" |
        head -1 |
        cut -d'"' -f2
    )"



    LGSM_PORT="$(
        grep -E '^port=' "${LGSM_COMMON_CFG}" |
        head -1 |
        cut -d'"' -f2
    )"



    LGSM_APPID="$(
        grep -E '^appid=' "${LGSM_COMMON_CFG}" |
        head -1 |
        cut -d'"' -f2
    )"



    LGSM_BEPATH="$(
        grep -E '^bepath=' "${LGSM_COMMON_CFG}" |
        head -1 |
        cut -d'"' -f2
    )"



    echo

    echo "Servidor LinuxGSM"

    echo "----------------------------------------"


    [[ -n "${LGSM_IP}" ]] &&
        echo "IP.............: ${LGSM_IP}"


    [[ -n "${LGSM_PORT}" ]] &&
        echo "Porta..........: ${LGSM_PORT}"



    echo

    echo "Steam"

    echo "----------------------------------------"


    [[ -n "${LGSM_APPID}" ]] &&
        echo "AppID..........: ${LGSM_APPID}"



    #
    # BattleEye
    #
    echo

    echo "BattleEye"

    echo "----------------------------------------"


    if [[ -n "${LGSM_BEPATH}" ]]
    then

        echo "Path...........: ${LGSM_BEPATH}"


        if [[ -d "${LGSM_BEPATH}" ]]
        then

            print_ok "Diretório BattleEye encontrado."

        else

            print_warn "Diretório BattleEye não encontrado."

        fi

    else

        echo "Path...........: padrão LinuxGSM"

    fi



    #
    # Mods
    #
    LGSM_MODS="$(
        grep '^mods=' "${LGSM_COMMON_CFG}" |
        sed 's/^mods="//' |
        sed 's/"$//' |
        sed 's/\\;/\n/g'
    )"



    echo

    echo "Mods LinuxGSM"

    echo "----------------------------------------"



    if [[ -n "${LGSM_MODS}" ]]
    then

        echo "${LGSM_MODS}"

    else

        echo "Nenhum mod configurado."

    fi



    #
    # Parâmetros de inicialização
    #
    echo

    echo "Start Parameters"

    echo "----------------------------------------"



    local start_params


    start_params="$(
        grep '^startparameters=' "${LGSM_COMMON_CFG}" |
        cut -d'"' -f2-
    )"



    if [[ -n "${start_params}" ]]
    then

        echo "${start_params}"

    else

        echo "Não encontrado."

    fi



    #
    # Alertas
    #
    echo

    echo "Alertas LinuxGSM"

    echo "----------------------------------------"



    local discord

    local email


    discord="$(
        grep '^discordalert=' "${LGSM_COMMON_CFG}" |
        cut -d'"' -f2
    )"


    email="$(
        grep '^emailalert=' "${LGSM_COMMON_CFG}" |
        cut -d'"' -f2
    )"



    echo "Discord........: ${discord:-off}"

    echo "Email..........: ${email:-off}"



    STATUS_LGSM_CONFIG="ok"


    return 0

}

# =============================================================
# Diagnóstico Serverfiles
# =============================================================

diagnose_serverfiles()
{

    print_title "Serverfiles"



    if [[ -z "${SERVERFILES_PATH:-}" ]]
    then

        print_fail "SERVERFILES_PATH não definido."

        set_failure

        return 1

    fi



    if [[ ! -d "${SERVERFILES_PATH}" ]]
    then

        print_fail "Diretório serverfiles não encontrado."

        echo "Local..........: ${SERVERFILES_PATH}"

        set_failure

        return 1

    fi



    print_ok "Diretório serverfiles encontrado."

    echo

    echo "Local..........: ${SERVERFILES_PATH}"



    #
    # Executável DayZ
    #

    local dayz_bin=""


    if [[ -x "${SERVERFILES_PATH}/DayZServer" ]]
    then

        dayz_bin="${SERVERFILES_PATH}/DayZServer"

    elif [[ -x "${SERVERFILES_PATH}/DayZServer_x64" ]]
    then

        dayz_bin="${SERVERFILES_PATH}/DayZServer_x64"

    fi



    if [[ -n "${dayz_bin}" ]]
    then

        print_ok "Executável DayZ encontrado."

        echo "Executável.....: ${dayz_bin}"

    else

        print_warn "Executável DayZ não encontrado."

    fi



    #
    # BattleEye
    #

    if [[ -d "${SERVERFILES_PATH}/battleye" ]]
    then

        print_ok "BattleEye encontrado."

    else

        print_warn "Diretório BattleEye não encontrado."

    fi



    #
    # Profiles
    #

    if [[ -d "${SERVERFILES_PATH}/profiles" ]]
    then

        print_ok "Profiles encontrado."

    else

        print_warn "Diretório Profiles não encontrado."

    fi



    #
    # Logs LinuxGSM
    #

    local lgsm_logdir


    lgsm_logdir="${LINUXGSM_PATH}/log"



    echo

    echo "Logs LinuxGSM"

    echo "----------------------------------------"



    if [[ -d "${lgsm_logdir}" ]]
    then

        print_ok "Diretório log encontrado."

        echo "Local..........: ${lgsm_logdir}"


        for folder in console script steam
        do

            if [[ -d "${lgsm_logdir}/${folder}" ]]
            then

                print_ok "log/${folder}"

            else

                print_warn "log/${folder} ausente."

            fi

        done


    else

        print_warn "Diretório log LinuxGSM não encontrado."

    fi



    return 0

}



# =============================================================
# Diagnóstico Configuração DayZ
# =============================================================

diagnose_config()
{

    print_title "Configuração DayZ"



    local cfg=""


    #
    # Configuração principal
    #

    if [[ -f "${SERVERFILES_PATH}/serverDZ.cfg" ]]
    then

        cfg="${SERVERFILES_PATH}/serverDZ.cfg"

    fi



    #
    # Config alternativa LinuxGSM
    #

    if [[ -f "${SERVERFILES_PATH}/cfg/dayzserver.server.cfg" ]]
    then

        cfg="${SERVERFILES_PATH}/cfg/dayzserver.server.cfg"

    fi



    if [[ -z "${cfg}" ]]
    then

        print_fail "Arquivo serverDZ.cfg não encontrado."

        set_failure

        return 1

    fi



    print_ok "Arquivo de configuração encontrado."

    echo

    echo "Arquivo.........: ${cfg}"



    #
    # Ler informações básicas
    #

    local hostname=""

    local maxplayers=""

    local password=""



    hostname="$(
        grep -E '^[[:space:]]*hostname' "${cfg}" |
        head -1 |
        cut -d'=' -f2- |
        tr -d ' ";'
    )"



    maxplayers="$(
        grep -E '^[[:space:]]*maxPlayers' "${cfg}" |
        head -1 |
        cut -d'=' -f2- |
        tr -d ' ";'
    )"



    password="$(
        grep -E '^[[:space:]]*password' "${cfg}" |
        head -1 |
        cut -d'=' -f2- |
        tr -d ' ";'
    )"



    [[ -n "${hostname}" ]] &&
        echo "Servidor........: ${hostname}"



    [[ -n "${maxplayers}" ]] &&
        echo "Max Players.....: ${maxplayers}"



    if [[ -n "${password}" ]]
    then

        echo "Senha...........: Configurada"

    else

        echo "Senha...........: Não definida"

    fi



    return 0

}

# =============================================================
# Diagnóstico Processo DayZ
# =============================================================

diagnose_process()
{

    print_title "Processo DayZ"



    PROCESS_PID=""

    PROCESS_CPU=""

    PROCESS_RAM=""



    #
    # Tentativa LinuxGSM
    #

    if [[ -n "${INSTANCE_NAME:-}" ]] &&
       [[ -x "${LINUXGSM_PATH}/${INSTANCE_NAME}" ]]
    then


        local lgsm_details


        lgsm_details="$(
            timeout 10 \
            "${LINUXGSM_PATH}/${INSTANCE_NAME}" details \
            2>/dev/null
        )"



        if echo "${lgsm_details}" |
            grep -q "Status:[[:space:]]*STARTED"
        then

            print_ok "LinuxGSM informa servidor iniciado."

        fi


    fi


    #
    # Procurar processo DayZ via DSM Server Module
    #

    if declare -F server_pid >/dev/null
    then

        PROCESS_PID="$(server_pid)"

    fi


    #
    # Fallback legado
    # Apenas caso o Server Module falhe
    #

    if [[ -z "${PROCESS_PID}" || "${PROCESS_PID}" == "0" ]]
    then

        PROCESS_PID="$(
            pgrep -f \
            '(^|/)(DayZServer|DayZServer_x64)( |$)' |
            head -n 1
        )"

    fi



    #
    # Processo não encontrado
    #

    if [[ -z "${PROCESS_PID}" ]]
    then

        print_fail "Servidor DayZ não está em execução."

        set_failure

        return 1

    fi



    print_ok "Servidor DayZ em execução."



    echo

    echo "PID.............: ${PROCESS_PID}"



    #
    # CPU
    #

    PROCESS_CPU="$(
        ps -p "${PROCESS_PID}" \
        -o %cpu= \
        2>/dev/null |
        xargs
    )"



    #
    # RAM
    #

    PROCESS_RAM="$(
        ps -p "${PROCESS_PID}" \
        -o rss= \
        2>/dev/null |
        xargs
    )"



    if [[ -n "${PROCESS_RAM}" ]]
    then

        PROCESS_RAM=$((PROCESS_RAM / 1024))

    fi



    [[ -n "${PROCESS_CPU}" ]] &&
        echo "CPU.............: ${PROCESS_CPU}%"



    [[ -n "${PROCESS_RAM}" ]] &&
        echo "RAM.............: ${PROCESS_RAM} MB"



    #
    # Tempo execução
    #

    local uptime



    uptime="$(
        ps -p "${PROCESS_PID}" \
        -o etime= \
        2>/dev/null |
        xargs
    )"



    [[ -n "${uptime}" ]] &&
        echo "Uptime..........: ${uptime}"



    #
    # Linha completa
    #

    local command_line



    command_line="$(
        ps -p "${PROCESS_PID}" \
        -o args= \
        2>/dev/null
    )"



    if [[ -n "${command_line}" ]]
    then

        echo

        echo "Linha execução"

        echo "----------------------------------------"

        echo "${command_line}"

    fi



    #
    # Validar portas DayZ
    #

    if command -v ss >/dev/null 2>&1
    then


        echo

        echo "Portas DayZ"

        echo "----------------------------------------"



        ss -lunp 2>/dev/null |
        grep -E \
        '2302|2303|2304|2305|2306|27016' ||
        echo "Nenhuma porta localizada."


    fi



    return 0

}

# =============================================================
# Diagnóstico Mods DayZ
# =============================================================

diagnose_mods()
{

    print_title "Mods"



    MOD_COUNT=0



    local mods_dir

    mods_dir="${SERVERFILES_PATH}/mods"



    #
    # Diretório de mods
    #

    if [[ ! -d "${mods_dir}" ]]
    then

        print_fail "Diretório de mods não encontrado."

        echo "Local..........: ${mods_dir}"

        set_failure

        return 1

    fi



    print_ok "Diretório de mods encontrado."

    echo

    echo "Local..........: ${mods_dir}"



    #
    # Contar mods
    #
    # Aceita:
    #   - diretório normal
    #   - link simbólico para diretório
    #

    while IFS= read -r -d ''
    do

        MOD_COUNT=$((MOD_COUNT+1))

    done < <(

        find "${mods_dir}" \
        -mindepth 1 \
        -maxdepth 1 \
        \( -type d -o -type l \) \
        -name "@*" \
        -print0

    )



    echo "Quantidade.....: ${MOD_COUNT}"



    echo

    echo "Mods instalados"

    echo "----------------------------------------"



    if (( MOD_COUNT == 0 ))
    then

        print_warn "Nenhum diretório de mod encontrado."

    else



        while read -r mod
        do


            local name

            name="$(basename "${mod}")"



            #
            # Verificar link quebrado
            #

            if [[ -L "${mod}" ]] &&
               [[ ! -e "${mod}" ]]
            then

                printf "%-35s [LINK QUEBRADO]\n" "${name}"

                set_failure

                continue

            fi



            #
            # Verificar meta.cpp
            #

            if [[ -f "${mod}/meta.cpp" ]]
            then

                printf "%-35s [OK]\n" "${name}"

            else

                printf "%-35s [SEM meta.cpp]\n" "${name}"

            fi



        done < <(

            find "${mods_dir}" \
            -mindepth 1 \
            -maxdepth 1 \
            \( -type d -o -type l \) \
            -name "@*" |
            sort

        )


    fi



    #
    # Configuração LinuxGSM
    #

    echo

    echo "Configuração LinuxGSM"

    echo "----------------------------------------"



    if [[ -n "${LGSM_MODS:-}" ]]
    then



        while IFS= read -r configured_mod
        do


            [[ -z "${configured_mod}" ]] && continue



            local mod_name

            mod_name="$(basename "${configured_mod}")"



            if [[ -e "${mods_dir}/${mod_name}" ]]
            then

                print_ok "${mod_name}"

            else

                print_fail "${mod_name} não encontrado."

                set_failure

            fi



        done <<< "${LGSM_MODS}"



    else

        print_warn "Nenhum mod configurado no LinuxGSM."

    fi



    #
    # Workshop Steam
    #

    echo

    echo "Workshop"

    echo "----------------------------------------"


    #
    # Linha -mod do processo
    #

    if [[ -n "${PROCESS_PID:-}" ]]
    then


        local cmdline



        cmdline="$(
            ps -p "${PROCESS_PID}" \
            -o args= \
            2>/dev/null
        )"



        echo

        echo "Parâmetro inicialização"

        echo "----------------------------------------"



        if [[ "${cmdline}" =~ -mod= ]]
        then

            print_ok "Parâmetro -mod encontrado."

        else

            print_warn "Servidor iniciado sem parâmetro -mod."

        fi


    fi



    #
    # Keys
    #

    echo

    echo "Keys"

    echo "----------------------------------------"



    if [[ -d "${SERVERFILES_PATH}/keys" ]]
    then


        local key_count



        key_count="$(
            find "${SERVERFILES_PATH}/keys" \
            -type f \
            -name "*.bikey" |
            wc -l
        )"



        echo "Chaves.........: ${key_count}"


    else

        print_warn "Diretório keys não encontrado."

    fi



    return 0

}


# =============================================================
# Diagnóstico Recursos do Sistema
# =============================================================

diagnose_resources()
{

    print_title "Recursos do Sistema"



    #
    # CPU
    #

    echo

    echo "CPU"

    echo "----------------------------------------"



    local cpu_model

    local cpu_cores

    local cpu_load



    cpu_model="$(
        lscpu 2>/dev/null |
        awk -F: '/Model name/ {
            gsub(/^[ \t]+/,"",$2);
            print $2;
            exit
        }'
    )"



    cpu_cores="$(nproc 2>/dev/null)"



    cpu_load="$(
        awk '{print $1,$2,$3}' /proc/loadavg
    )"



    [[ -n "${cpu_model}" ]] &&
        echo "Modelo.........: ${cpu_model}"



    [[ -n "${cpu_cores}" ]] &&
        echo "Núcleos........: ${cpu_cores}"



    [[ -n "${cpu_load}" ]] &&
        echo "Load Average...: ${cpu_load}"



    #
    # Memória
    #

    echo

    echo "Memória"

    echo "----------------------------------------"



    free -h



    #
    # Disco
    #

    echo

    echo "Disco"

    echo "----------------------------------------"



    df -h "${SERVERFILES_PATH}" 2>/dev/null



    #
    # Sistema
    #

    echo

    echo "Sistema"

    echo "----------------------------------------"



    echo "Hostname.......: $(hostname)"

    echo "Kernel.........: $(uname -r)"

    echo "Arquitetura....: $(uname -m)"

    echo "Uptime.........: $(uptime -p)"



    #
    # Rede
    #

    echo

    echo "Rede"

    echo "----------------------------------------"



    local ip_local



    ip_local="$(
        hostname -I 2>/dev/null |
        awk '{print $1}'
    )"



    [[ -n "${ip_local}" ]] &&
        echo "IP Local.......: ${ip_local}"



    #
    # Portas DayZ
    #

    echo

    echo "Portas DayZ"

    echo "----------------------------------------"



    if command -v ss >/dev/null 2>&1
    then


        ss -lunp 2>/dev/null |
        grep -E \
        '2302|2303|2304|2305|2306|27016' ||
        echo "Nenhuma porta encontrada."


    else

        echo "Comando ss indisponível."

    fi



    #
    # Processo DayZ
    #

    if [[ -n "${PROCESS_PID:-}" ]]
    then


        echo

        echo "Uso processo DayZ"

        echo "----------------------------------------"



        ps -p "${PROCESS_PID}" \
        -o pid,%cpu,%mem,rss,etime,cmd


    fi



    #
    # Temperatura
    #

    if command -v sensors >/dev/null 2>&1
    then


        echo

        echo "Temperatura"

        echo "----------------------------------------"



        sensors 2>/dev/null || true


    fi



    return 0

}





# =============================================================
# Execução principal do diagnóstico
# =============================================================

monitor_diagnose_run()
{
    local SERVER_STATUS
    local HEALTH
    local PID
    local CPU
    local MEMORY
    local DISK
    local EVENTS
    local LAST_CHECK
    local SERVER_JSON
    local METRICS_JSON

    SERVER_STATUS=$(
        runtime_get server |
        python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status","unknown"))'
    )

    SERVER_JSON="$(runtime_get server)"

    HEALTH=$(
    echo "$SERVER_JSON" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("health","unknown"))'
    )

    PID=$(
    echo "$SERVER_JSON" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("pid","-"))'
    )

    LAST_CHECK=$(
    echo "$SERVER_JSON" |
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("last_check","-"))'
    )

    METRICS_JSON="$(runtime_get metrics)"


    CPU=$(
        echo "$METRICS_JSON" |
        python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("cpu",{}).get("host_pct","-"))'
    )


    MEMORY=$(
        echo "$METRICS_JSON" |
        python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("memory",{}).get("dayz_pct","-"))'
    )


    DISK=$(
        echo "$METRICS_JSON" |
        python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("disk",{}).get("used_pct","-"))'
    )

    EVENTS=$(json_value "$EVENTS_STATE" total)

    echo
    echo "============================================================"
    echo " DSM - Monitor"
    echo "============================================================"
    echo

    printf "%-24s %s\n"   "Servidor:"             "$SERVER_STATUS"
    printf "%-24s %s\n"   "Health:"               "$HEALTH"
    printf "%-24s %s\n"   "PID:"                  "$PID"
    printf "%-24s %s%%\n" "CPU:"                  "$CPU"
    printf "%-24s %s%%\n" "Memória:"              "$MEMORY"
    printf "%-24s %s%%\n" "Disco:"                "$DISK"
    printf "%-24s %s\n"   "Eventos:"              "$EVENTS"
    printf "%-24s %s\n"   "Última verificação:"   "$LAST_CHECK"

    echo

    if [[ "$SERVER_STATUS" == "online" ]]
    then
        echo "Status geral............... OK"
        return 0
    fi

    echo "Status geral............... ALERTA"
    return 1
}

# =============================================================
# Compatibilidade Doctor
# =============================================================

diagnose_run()
{

    monitor_diagnose_run "$@"

}



# =============================================================
# API simples Dashboard
# =============================================================

monitor_status_json()
{

cat <<EOF
{
  "instance":"${INSTANCE_NAME:-}",
  "pid":"${PROCESS_PID:-}",
  "cpu":"${PROCESS_CPU:-}",
  "ram":"${PROCESS_RAM:-}",
  "mods":"${MOD_COUNT:-0}",
  "linuxgsm":"${STATUS_LGSM:-unknown}",
  "linuxgsm_config":"${STATUS_LGSM_CONFIG:-unknown}",
  "status":"$(
      if [[ "${MONITOR_STATUS:-1}" -eq 0 ]]
      then
          echo healthy
      else
          echo warning
      fi
  )"
}
EOF

}

doctor_runtime_get()
{
    local MODULE="$1"

    runtime_get "$MODULE"
}

# =============================================================
# Exportar funções para módulos DSM
# =============================================================

export -f metrics_value
export -f diagnose_lgsm
export -f diagnose_lgsm_config
export -f diagnose_serverfiles
export -f diagnose_config
export -f diagnose_process
export -f diagnose_mods
export -f diagnose_resources
export -f monitor_diagnose_run
export -f diagnose_run
export -f monitor_status_json



# =============================================================
# Execução direta
#
# Executa somente quando:
#
# ./diagnose.sh
#
# ou:
#
# bash diagnose.sh
#
# Quando carregado via source:
#
# source diagnose.sh
#
# não executa automaticamente.
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    monitor_diagnose_run "$@"

fi
