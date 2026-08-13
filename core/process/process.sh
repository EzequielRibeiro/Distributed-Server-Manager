#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# Process Engine
#
# Responsável por:
#
# - iniciar processo
# - parar processo
# - reiniciar processo
# - verificar processo
# - obter PID
# - obter informações
# - controlar PID da instância
#
# Arquitetura:
#
#   GAME_INSTALL
#       │
#       └── executável do jogo
#
#   INSTANCE_PATH
#       │
#       ├── instance.conf
#       └── runtime/
#           ├── process.pid
#           └── instance.log
#
# Sem dependência de LinuxGSM.
#
# =============================================================

set -Eeuo pipefail

# =============================================================
# RESOLVE EXECUTABLE
# =============================================================

resolve_executable()
{
    local INSTANCE_PATH="$1"

    if [[ ! -f "${INSTANCE_PATH}/instance.conf" ]]
    then
        echo "Configuração da instância não encontrada:"
        echo "${INSTANCE_PATH}/instance.conf" >&2
        return 1
    fi

    source "${INSTANCE_PATH}/instance.conf"

    if [[ -z "${GAME_INSTALL:-}" ]]
    then
        echo "GAME_INSTALL não definido." >&2
        return 1
    fi

    if [[ -z "${EXECUTABLE:-}" ]]
    then
        echo "EXECUTABLE não definido." >&2
        return 1
    fi

    echo "${GAME_INSTALL}/${EXECUTABLE}"
}

# =============================================================
# SYSTEMD USER UNIT
#
# Cada instância executa em uma transient unit própria.
#
# Isto desacopla o processo do jogo do processo que solicitou
# sua inicialização (Dashboard, CLI, Scheduler, Agent etc.).
#
# Exemplo:
#
#   capivara-instance-cli-demo-001-minecraft-001.service
#
# =============================================================

process_prepare_user_bus()
{
    #
    # Process Engine pode ser chamado por:
    #
    # - shell interativo
    # - Dashboard systemd
    # - Scheduler
    # - Agent
    #
    # Serviços systemd de sistema executados como usuário comum
    # não recebem necessariamente o ambiente da sessão systemd --user.
    #
    # Portanto resolvemos explicitamente o runtime dir e o D-Bus
    # do usuário executor.
    #

    local USER_UID

    USER_UID="$(id -u)"

    if [[ -z "${XDG_RUNTIME_DIR:-}" ]]
    then
        export XDG_RUNTIME_DIR="/run/user/${USER_UID}"
    fi

    if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]
    then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    fi

    if [[ ! -d "${XDG_RUNTIME_DIR}" ]]
    then
        echo "Systemd user runtime directory não encontrado:" >&2
        echo "${XDG_RUNTIME_DIR}" >&2
        return 1
    fi

    if [[ ! -S "${XDG_RUNTIME_DIR}/bus" ]]
    then
        echo "Systemd user D-Bus não encontrado:" >&2
        echo "${XDG_RUNTIME_DIR}/bus" >&2
        return 1
    fi

    if ! systemctl --user is-system-running \
        >/dev/null 2>&1
    then
        echo "Systemd user manager não está disponível." >&2
        return 1
    fi

    return 0
}


process_unit_name()
{
    local INSTANCE_PATH="$1"

    if [[ ! -f "${INSTANCE_PATH}/instance.conf" ]]
    then
        return 1
    fi

    local INSTANCE_ID=""

    #
    # instance.conf é a fonte oficial da identidade.
    #
    source "${INSTANCE_PATH}/instance.conf"

    if [[ -z "${INSTANCE_ID:-}" ]]
    then
        INSTANCE_ID="$(basename "${INSTANCE_PATH}")"
    fi

    #
    # Nome seguro para systemd.
    #
    local SAFE_ID

    SAFE_ID="$(
        printf '%s' "${INSTANCE_ID}" |
        tr -c 'A-Za-z0-9_.@-' '-'
    )"

    printf 'capivara-instance-%s.service\n' "${SAFE_ID}"
}


process_unit_file()
{
    local INSTANCE_PATH="$1"

    printf '%s/runtime/process.unit\n' \
        "${INSTANCE_PATH}"
}


process_unit()
{
    local INSTANCE_PATH="$1"
    local UNITFILE

    UNITFILE="$(process_unit_file "${INSTANCE_PATH}")"

    if [[ -s "${UNITFILE}" ]]
    then
        cat "${UNITFILE}"
        return 0
    fi

    process_unit_name "${INSTANCE_PATH}"
}


process_unit_exists()
{
    local INSTANCE_PATH="$1"
    local UNIT

    process_prepare_user_bus >/dev/null 2>&1 ||
        return 1

    UNIT="$(process_unit "${INSTANCE_PATH}" 2>/dev/null)" ||
        return 1

    systemctl --user show \
        "${UNIT}" \
        -p LoadState \
        --value \
        2>/dev/null |
        grep -qxv 'not-found'
}


process_unit_active()
{
    local INSTANCE_PATH="$1"
    local UNIT

    process_prepare_user_bus >/dev/null 2>&1 ||
        return 1

    UNIT="$(process_unit "${INSTANCE_PATH}" 2>/dev/null)" ||
        return 1

    systemctl --user is-active \
        --quiet \
        "${UNIT}" \
        2>/dev/null
}


process_unit_main_pid()
{
    local INSTANCE_PATH="$1"
    local UNIT

    process_prepare_user_bus >/dev/null 2>&1 ||
        return 1

    UNIT="$(process_unit "${INSTANCE_PATH}" 2>/dev/null)" ||
        return 1

    local PID

    PID="$(
        systemctl --user show \
            "${UNIT}" \
            -p MainPID \
            --value \
            2>/dev/null
    )"

    if [[ "${PID}" =~ ^[0-9]+$ ]] &&
       (( PID > 0 ))
    then
        printf '%s\n' "${PID}"
        return 0
    fi

    return 1
}


process_cleanup_stale()
{
    local INSTANCE_PATH="$1"

    local PIDFILE
    local UNITFILE

    PIDFILE="$(process_pidfile "${INSTANCE_PATH}")"
    UNITFILE="$(process_unit_file "${INSTANCE_PATH}")"

    #
    # Se a unit está ativa, não existe estado stale.
    #
    if process_unit_active "${INSTANCE_PATH}"
    then
        return 0
    fi

    #
    # Compatibilidade com processos iniciados pelo engine antigo.
    #
    if [[ -f "${PIDFILE}" ]]
    then
        local PID

        PID="$(cat "${PIDFILE}" 2>/dev/null || true)"

        if [[ "${PID}" =~ ^[0-9]+$ ]] &&
           kill -0 "${PID}" 2>/dev/null
        then
            return 0
        fi

        rm -f "${PIDFILE}"
    fi

    #
    # process.unit pode permanecer enquanto a transient unit
    # estiver registrada como inactive/failed. O arquivo ainda
    # é útil para diagnóstico e stop/reset posteriores.
    #
    return 0
}


# =============================================================
# PID FILE
# =============================================================

process_pidfile()
{
    local INSTANCE_PATH="$1"

    echo "${INSTANCE_PATH}/runtime/process.pid"
}

# =============================================================
# LOG FILE
# =============================================================

process_logfile()
{
    local INSTANCE_PATH="$1"

    echo "${INSTANCE_PATH}/runtime/instance.log"
}

# =============================================================
# LÊ PID
# =============================================================

process_pid()
{
    local INSTANCE_PATH="$1"

    local PIDFILE
    PIDFILE="$(process_pidfile "${INSTANCE_PATH}")"

    if [[ ! -f "${PIDFILE}" ]]
    then
        return 1
    fi

    local PID
    PID="$(cat "${PIDFILE}")"

    if [[ -z "${PID}" ]]
    then
        return 1
    fi

    echo "${PID}"
}

# =============================================================
# VALIDA PID
# =============================================================

process_pid_validate()
{
    local PID="$1"

    if [[ ! "${PID}" =~ ^[0-9]+$ ]]
    then
        return 1
    fi

    if ! kill -0 "${PID}" 2>/dev/null
    then
        return 1
    fi

    return 0
}

# =============================================================
# PROCESS RUNNING
# =============================================================

process_running()
{
    local INSTANCE_PATH="$1"

    #
    # Runtime novo:
    # a transient unit do systemd é a fonte principal.
    #
    if process_unit_active "${INSTANCE_PATH}"
    then
        local PID

        PID="$(
            process_unit_main_pid "${INSTANCE_PATH}" 2>/dev/null
        )" || return 1

        #
        # Mantemos process.pid como cache/compatibilidade para
        # módulos que ainda consultam esse arquivo.
        #
        mkdir -p "${INSTANCE_PATH}/runtime"

        printf '%s\n' "${PID}" \
            > "$(process_pidfile "${INSTANCE_PATH}")"

        return 0
    fi

    #
    # Compatibilidade com processos iniciados pelo engine antigo.
    #
    local PID

    PID="$(
        process_pid "${INSTANCE_PATH}" 2>/dev/null
    )" || {
        process_cleanup_stale "${INSTANCE_PATH}"
        return 1
    }

    if process_pid_validate "${PID}"
    then
        return 0
    fi

    process_cleanup_stale "${INSTANCE_PATH}"

    return 1
}

# =============================================================
# START
# =============================================================

process_start()
{
    local INSTANCE_PATH="$1"

    # ---------------------------------------------------------
    # Validação da instância
    # ---------------------------------------------------------

    if [[ ! -d "${INSTANCE_PATH}" ]]
    then
        echo "Diretório da instância não encontrado:"
        echo "${INSTANCE_PATH}" >&2
        return 1
    fi

    # ---------------------------------------------------------
    # Configuração
    # ---------------------------------------------------------

    local INSTANCE_CONF="${INSTANCE_PATH}/instance.conf"

    if [[ ! -f "${INSTANCE_CONF}" ]]
    then
        echo "Configuração da instância não encontrada:"
        echo "${INSTANCE_CONF}" >&2
        return 1
    fi

    source "${INSTANCE_CONF}"

    # ---------------------------------------------------------
    # Runtime
    # ---------------------------------------------------------

    local RUNTIME_DIR="${INSTANCE_PATH}/runtime"

    local PIDFILE="${RUNTIME_DIR}/process.pid"

    local LOGFILE="${RUNTIME_DIR}/instance.log"

    mkdir -p "${RUNTIME_DIR}"

    touch "${LOGFILE}"

    # ---------------------------------------------------------
    # Já executando?
    # ---------------------------------------------------------

    if process_running "${INSTANCE_PATH}"
    then
        local EXISTING_PID

        EXISTING_PID="$(process_pid "${INSTANCE_PATH}")"

        echo "Processo já está em execução."
        echo "PID: ${EXISTING_PID}"

        return 0
    fi

    # ---------------------------------------------------------
    # Remove PID antigo
    # ---------------------------------------------------------

    rm -f "${PIDFILE}"

    # ---------------------------------------------------------
    # Validação GAME_INSTALL
    # ---------------------------------------------------------

    if [[ -z "${GAME_INSTALL:-}" ]]
    then
        echo "GAME_INSTALL não definido." >&2
        return 1
    fi

    if [[ ! -d "${GAME_INSTALL}" ]]
    then
        echo "Instalação do jogo não encontrada:"
        echo "${GAME_INSTALL}" >&2
        return 1
    fi

    # ---------------------------------------------------------
    # Validação EXECUTABLE
    # ---------------------------------------------------------

    if [[ -z "${EXECUTABLE:-}" ]]
    then
        echo "EXECUTABLE não definido." >&2
        return 1
    fi

    local EXECUTABLE_PATH="${GAME_INSTALL}/${EXECUTABLE}"

    if [[ ! -f "${EXECUTABLE_PATH}" ]]
    then
        echo "Executável não encontrado:"
        echo "${EXECUTABLE_PATH}" >&2
        return 1
    fi

    case "${PROCESS_ENGINE:-native}" in
        java|jar)
            if [[ -n "${JAVA_BIN:-}" ]]
            then
                if [[ ! -x "${JAVA_BIN}" ]]
                then
                    echo "Java configurado não encontrado ou não executável:" >&2
                    echo "${JAVA_BIN}" >&2
                    return 1
                fi
            elif ! command -v java >/dev/null 2>&1
            then
                echo "Java não está instalado ou não está disponível no PATH." >&2
                return 1
            fi
            ;;

        native|executable|"")
            if [[ ! -x "${EXECUTABLE_PATH}" ]]
            then
                chmod +x "${EXECUTABLE_PATH}" 2>/dev/null || {
                    echo "Executável não possui permissão de execução:"
                    echo "${EXECUTABLE_PATH}" >&2
                    return 1
                }
            fi
            ;;

        *)
            echo "Process engine não suportado: ${PROCESS_ENGINE}" >&2
            return 1
            ;;
    esac

    # ---------------------------------------------------------
    # Diretório de trabalho
    #
    # Por padrão usamos a instalação do jogo.
    #
    # Caso WORKING_DIR seja definido, ele é relativo ao
    # GAME_INSTALL.
    # ---------------------------------------------------------

    local WORKDIR="${GAME_INSTALL}"

    if [[ -n "${WORKING_DIR:-}" ]]
    then
        WORKDIR="${GAME_INSTALL}/${WORKING_DIR}"
    fi

    if [[ ! -d "${WORKDIR}" ]]
    then
        echo "Diretório de trabalho não encontrado:"
        echo "${WORKDIR}" >&2
        return 1
    fi

    # ---------------------------------------------------------
    # Início
    # ---------------------------------------------------------

    echo "Iniciando processo..."
    echo "Instance : ${INSTANCE_ID:-unknown}"
    echo "Game     : ${GAME:-unknown}"
    echo "Install  : ${GAME_INSTALL}"
    echo "Workdir  : ${WORKDIR}"
    echo "Executable: ${EXECUTABLE_PATH}"

    # ---------------------------------------------------------
    # Executa processo
    #
    # O processo da instância NÃO deve pertencer ao cgroup do
    # Dashboard, Scheduler, CLI ou Agent que solicitou o start.
    #
    # Cada instância recebe sua própria transient user unit:
    #
    #   capivara-instance-<INSTANCE_ID>.service
    #
    # ---------------------------------------------------------

    local UNIT
    local UNITFILE

    process_prepare_user_bus || {
        echo "Não foi possível acessar o systemd --user." >&2
        return 1
    }

    UNIT="$(process_unit_name "${INSTANCE_PATH}")"
    UNITFILE="$(process_unit_file "${INSTANCE_PATH}")"

    #
    # Limpa eventual estado failed/inactive de uma execução
    # anterior com o mesmo nome.
    #
    systemctl --user reset-failed "${UNIT}" \
        >/dev/null 2>&1 || true

    local -a PROCESS_ARGS=()

    if [[ -n "${ARGS:-}" ]]
    then
        read -r -a PROCESS_ARGS <<< "${ARGS}"
    fi

    local -a COMMAND=()

    case "${PROCESS_ENGINE:-native}" in

        java|jar)

            local LOCAL_JAVA
            LOCAL_JAVA="${JAVA_BIN:-$(command -v java)}"

            COMMAND=(
                "${LOCAL_JAVA}"
                -jar
                "${EXECUTABLE_PATH}"
                "${PROCESS_ARGS[@]}"
            )
            ;;

        native|executable|"")

            COMMAND=(
                "${EXECUTABLE_PATH}"
                "${PROCESS_ARGS[@]}"
            )
            ;;

        *)

            echo \
                "Process engine não suportado: ${PROCESS_ENGINE}" \
                >> "${LOGFILE}"

            return 1
            ;;

    esac

    echo "Unit     : ${UNIT}"

    if ! systemd-run \
        --user \
        --unit="${UNIT}" \
        --property="Type=simple" \
        --property="WorkingDirectory=${WORKDIR}" \
        --property="StandardOutput=append:${LOGFILE}" \
        --property="StandardError=append:${LOGFILE}" \
        --collect \
        -- \
        "${COMMAND[@]}"
    then
        echo "Falha ao criar transient unit da instância." >&2
        return 1
    fi

    #
    # Registrar a identidade da unit utilizada pela instância.
    #
    printf '%s\n' "${UNIT}" > "${UNITFILE}"

    # ---------------------------------------------------------
    # Obtém PID real do systemd
    # ---------------------------------------------------------

    local PID=""
    local i

    for i in {1..20}
    do
        PID="$(
            process_unit_main_pid "${INSTANCE_PATH}" 2>/dev/null ||
            true
        )"

        if [[ "${PID}" =~ ^[0-9]+$ ]] &&
           (( PID > 0 ))
        then
            break
        fi

        sleep 0.25
    done

    if [[ ! "${PID}" =~ ^[0-9]+$ ]] ||
       (( PID <= 0 ))
    then
        echo "Systemd não forneceu MainPID válido." >&2

        systemctl --user status \
            "${UNIT}" \
            --no-pager \
            -l \
            2>/dev/null || true

        return 1
    fi

    printf '%s\n' "${PID}" > "${PIDFILE}"

    echo "PID: ${PID}"

    # ---------------------------------------------------------
    # Aguarda inicialização
    # ---------------------------------------------------------

    sleep 1

    # ---------------------------------------------------------
    # Verifica processo / unit
    # ---------------------------------------------------------

    if process_unit_active "${INSTANCE_PATH}" &&
       process_pid_validate "${PID}"
    then
        echo "Processo iniciado com sucesso."
        echo "Unit: ${UNIT}"

        return 0
    fi

    # ---------------------------------------------------------
    # Processo morreu durante inicialização
    # ---------------------------------------------------------

    echo "Processo terminou durante a inicialização."

    echo
    echo "Últimas mensagens do log:"
    echo "----------------------------------------"

    tail -30 "${LOGFILE}" 2>/dev/null || true

    echo "----------------------------------------"

    rm -f "${PIDFILE}"

    if [[ -n "${UNIT:-}" ]]
    then
        systemctl --user stop "${UNIT}"             >/dev/null 2>&1 || true

        systemctl --user reset-failed "${UNIT}"             >/dev/null 2>&1 || true
    fi

    return 1
}

# =============================================================
# STOP
# =============================================================

process_stop()
{
    local INSTANCE_PATH="$1"

    # ---------------------------------------------------------
    # Limpeza inicial de estado stale
    # ---------------------------------------------------------

    process_cleanup_stale "${INSTANCE_PATH}"

    local PIDFILE
    local UNITFILE
    local UNIT=""

    PIDFILE="$(process_pidfile "${INSTANCE_PATH}")"
    UNITFILE="$(process_unit_file "${INSTANCE_PATH}")"

    UNIT="$(
        process_unit "${INSTANCE_PATH}" 2>/dev/null || true
    )"

    # ---------------------------------------------------------
    # Runtime gerenciado pelo systemd --user
    # ---------------------------------------------------------

    if [[ -n "${UNIT}" ]] &&
       process_unit_exists "${INSTANCE_PATH}"
    then
        if process_unit_active "${INSTANCE_PATH}"
        then
            echo "Parando processo via systemd:"
            echo "Unit: ${UNIT}"

            if ! systemctl --user stop "${UNIT}"
            then
                echo "Falha ao parar unit systemd:" >&2
                echo "${UNIT}" >&2
                return 1
            fi

            local i

            for i in {1..15}
            do
                if ! process_unit_active "${INSTANCE_PATH}"
                then
                    break
                fi

                sleep 1
            done

            if process_unit_active "${INSTANCE_PATH}"
            then
                echo "A unit não encerrou dentro do tempo esperado:" >&2
                echo "${UNIT}" >&2
                return 1
            fi

            systemctl --user reset-failed \
                "${UNIT}" \
                >/dev/null 2>&1 || true

            rm -f "${PIDFILE}"

            echo "Processo encerrado."
            return 0
        fi

        #
        # A unit existe, mas já está inativa.
        #
        systemctl --user reset-failed \
            "${UNIT}" \
            >/dev/null 2>&1 || true

        rm -f "${PIDFILE}"

        echo "Processo não está em execução."
        return 0
    fi

    # ---------------------------------------------------------
    # Compatibilidade com runtime legado baseado em PID
    # ---------------------------------------------------------

    local PID

    PID="$(
        process_pid "${INSTANCE_PATH}" 2>/dev/null
    )" || {
        rm -f "${PIDFILE}"
        echo "Processo não está em execução."
        return 0
    }

    if ! process_pid_validate "${PID}"
    then
        echo "PID inválido ou processo já encerrado."

        rm -f "${PIDFILE}"

        return 0
    fi

    echo "Parando processo legado:"
    echo "PID: ${PID}"

    kill "${PID}" 2>/dev/null || true

    # ---------------------------------------------------------
    # Aguarda encerramento
    # ---------------------------------------------------------

    local i

    for i in {1..10}
    do
        if ! kill -0 "${PID}" 2>/dev/null
        then
            rm -f "${PIDFILE}"

            echo "Processo encerrado."
            return 0
        fi

        sleep 1
    done

    # ---------------------------------------------------------
    # Força encerramento somente no fallback legado
    # ---------------------------------------------------------

    echo "Processo não encerrou normalmente."
    echo "Enviando SIGKILL..."

    kill -9 "${PID}" 2>/dev/null || true

    sleep 1

    rm -f "${PIDFILE}"

    echo "Processo encerrado."

    return 0
}

# =============================================================
# RESTART
# =============================================================

process_restart()
{
    local INSTANCE_PATH="$1"

    process_stop "${INSTANCE_PATH}"

    sleep 1

    process_start "${INSTANCE_PATH}"
}

# =============================================================
# STATUS
# =============================================================

process_status()
{
    local INSTANCE_PATH="$1"

    local PID

    if PID="$(process_pid "${INSTANCE_PATH}" 2>/dev/null)"
    then

        if process_pid_validate "${PID}"
        then
            echo "Status: online"
            echo "PID: ${PID}"

            return 0
        fi
    fi

    echo "Status: offline"

    return 1
}

# =============================================================
# INFO
# =============================================================

process_info()
{
    local INSTANCE_PATH="$1"

    if [[ ! -f "${INSTANCE_PATH}/instance.conf" ]]
    then
        echo "Configuração não encontrada."
        return 1
    fi

    source "${INSTANCE_PATH}/instance.conf"

    echo "Instance      : ${INSTANCE_ID:-}"
    echo "Game          : ${GAME:-}"
    echo "Game Install  : ${GAME_INSTALL:-}"
    echo "Working Dir   : ${WORKING_DIR:-}"
    echo "Executable    : ${EXECUTABLE:-}"
    echo "Arguments     : ${ARGS:-}"

    if process_running "${INSTANCE_PATH}"
    then
        echo "Status        : online"
        echo "PID           : $(process_pid "${INSTANCE_PATH}")"
    else
        echo "Status        : offline"
    fi
}

# =============================================================
# UPTIME
# =============================================================

process_uptime()
{
    local INSTANCE_PATH="$1"

    local PID

    PID="$(process_pid "${INSTANCE_PATH}" 2>/dev/null)" || {
        return 1
    }

    process_pid_validate "${PID}" || return 1

    ps -p "${PID}" -o etime= | xargs
}

# =============================================================
# EXPORT API
# =============================================================

export -f resolve_executable
export -f process_prepare_user_bus
export -f process_unit_name
export -f process_unit_file
export -f process_unit
export -f process_unit_exists
export -f process_unit_active
export -f process_unit_main_pid
export -f process_cleanup_stale


export -f process_pidfile
export -f process_logfile

export -f process_pid
export -f process_pid_validate
export -f process_running

export -f process_start
export -f process_stop
export -f process_restart

export -f process_status
export -f process_info
export -f process_uptime

