#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
#
# DayZ Runtime
#
# Responsável por:
#
# - definir a integração do DayZ com o DSM
# - resolver a instalação do jogo
# - iniciar/parar/reiniciar a instância
# - validar a instalação
#
# Arquitetura:
#
#   Game Installation
#       │
#       └── /opt/dsm/game-data/dayz/serverfiles
#                │
#                └── DayZServer
#
#   Instance
#       │
#       └── /opt/dsm/instances/<node>/dayz/<instance>
#
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

# =============================================================
# GAME
# =============================================================

GAME_ID="dayz"

export GAME_ID

# =============================================================
# GAME INSTALLATION
# =============================================================

GAME_INSTALL="${GAME_INSTALL:-${DSM_ROOT}/game-data/${GAME_ID}/serverfiles}"

export GAME_INSTALL

# =============================================================
# EXECUTABLE
# =============================================================

EXECUTABLE="${EXECUTABLE:-DayZServer}"

export EXECUTABLE

# =============================================================
# WORKING DIRECTORY
#
# O DayZ utiliza a própria instalação como diretório de trabalho.
# =============================================================

WORKING_DIR="${WORKING_DIR:-}"

export WORKING_DIR

# =============================================================
# ARGUMENTOS
# =============================================================

ARGS="${ARGS:-}"

export ARGS

# =============================================================
# RESOLVE EXECUTABLE
# =============================================================

runtime_executable()
{
    echo "${GAME_INSTALL}/${EXECUTABLE}"
}

# =============================================================
# VALIDATE INSTALLATION
# =============================================================

runtime_validate_installation()
{
    local EXEC_PATH

    EXEC_PATH="$(runtime_executable)"

    echo "Validando instalação do DayZ..."
    echo "Game Install : ${GAME_INSTALL}"
    echo "Executable   : ${EXEC_PATH}"

    if [[ ! -d "${GAME_INSTALL}" ]]
    then
        echo
        echo "Instalação do DayZ não encontrada:"
        echo "${GAME_INSTALL}"
        return 1
    fi

    if [[ ! -f "${EXEC_PATH}" ]]
    then
        echo
        echo "Executável do DayZ não encontrado:"
        echo "${EXEC_PATH}"
        return 1
    fi

    if [[ ! -x "${EXEC_PATH}" ]]
    then
        chmod +x "${EXEC_PATH}" 2>/dev/null || {
            echo
            echo "Executável sem permissão de execução:"
            echo "${EXEC_PATH}"
            return 1
        }
    fi

    echo "Instalação válida."

    return 0
}

# =============================================================
# START
# =============================================================

runtime_start()
{
    local INSTANCE_PATH

    INSTANCE_PATH="$(get_instance_path)"

    echo "DayZ Runtime"
    echo "============"
    echo
    echo "Instance:"
    echo "${INSTANCE_PATH}"
    echo
    echo "Game Install:"
    echo "${GAME_INSTALL}"
    echo
    echo "Executable:"
    echo "$(runtime_executable)"
    echo

    runtime_validate_installation || return 1

    process_start "${INSTANCE_PATH}"
}

# =============================================================
# STOP
# =============================================================

runtime_stop()
{
    local INSTANCE_PATH

    INSTANCE_PATH="$(get_instance_path)"

    process_stop "${INSTANCE_PATH}"
}

# =============================================================
# RESTART
# =============================================================

runtime_restart()
{
    local INSTANCE_PATH

    INSTANCE_PATH="$(get_instance_path)"

    runtime_validate_installation || return 1

    process_restart "${INSTANCE_PATH}"
}

# =============================================================
# STATUS
# =============================================================

runtime_status()
{
    local INSTANCE_PATH

    INSTANCE_PATH="$(get_instance_path)"

    process_status "${INSTANCE_PATH}"
}

# =============================================================
# PID
# =============================================================

runtime_pid()
{
    local INSTANCE_PATH

    INSTANCE_PATH="$(get_instance_path)"

    process_pid "${INSTANCE_PATH}"
}

# =============================================================
# INFO
# =============================================================

runtime_info()
{
    local INSTANCE_PATH
    local PID
    local STATUS
    local CPU
    local MEMORY
    local UPTIME
    local CHILDREN

    INSTANCE_PATH="$(get_instance_path)"

    PID="$(process_pid "${INSTANCE_PATH}" 2>/dev/null || true)"

    if [[ -n "${PID}" ]] && process_pid_validate "${PID}"
    then
        STATUS="online"

        CPU="$(ps -p "${PID}" -o %cpu= 2>/dev/null | xargs || true)"
        MEMORY="$(ps -p "${PID}" -o rss= 2>/dev/null | xargs || true)"
        UPTIME="$(ps -p "${PID}" -o etimes= 2>/dev/null | xargs || true)"
        CHILDREN="$(pgrep -P "${PID}" 2>/dev/null | wc -l | xargs)"
    else
        STATUS="offline"
        PID=0
        CPU=0
        MEMORY=0
        UPTIME=0
        CHILDREN=0
    fi

    cat <<EOF
{
  "status": "${STATUS}",
  "pid": ${PID},
  "cpu": "${CPU:-0}",
  "memory": "${MEMORY:-0}",
  "uptime": "${UPTIME:-0}",
  "children": "${CHILDREN:-0}"
}
EOF
}

# =============================================================
# HEALTH
# =============================================================

runtime_health()
{
    local INSTANCE_PATH

    INSTANCE_PATH="$(get_instance_path)"

    runtime_validate_installation || return 1

    process_running "${INSTANCE_PATH}"
}

# =============================================================
# LAUNCHER
# =============================================================

runtime_launcher()
{
    get_instance_launcher
}

# =============================================================
# EXPORT API
# =============================================================

export -f runtime_executable
export -f runtime_validate_installation

export -f runtime_start
export -f runtime_stop
export -f runtime_restart
export -f runtime_status
export -f runtime_pid
export -f runtime_info
export -f runtime_health
export -f runtime_launcher
