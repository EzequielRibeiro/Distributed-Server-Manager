#!/usr/bin/env bash

# Canonical interactive Steam authentication for Linux Agent / Hybrid.
# Authentication always runs in the same OS user, HOME and SteamCMD resolver
# context used by the Agent runtime. Passwords and Steam Guard secrets are
# handled only by SteamCMD and are never read or persisted by Capivara.

steam_auth_error()
{
    printf '[DSM][STEAM][ERRO] %s\n' "$*" >&2
}

steam_auth_read_user()
{
    local ROOT="${1:-/opt/dsm}"
    local CONF="${ROOT}/config/providers/steam.conf"
    local LINE=""
    local VALUE=""

    [[ -r "${CONF}" ]] || {
        steam_auth_error "Configuração Steam não encontrada: ${CONF}"
        return 1
    }

    while IFS= read -r LINE || [[ -n "${LINE}" ]]
    do
        if [[ "${LINE}" =~ ^[[:space:]]*DSM_STEAM_USER[[:space:]]*=[[:space:]]*(.*)[[:space:]]*$ ]]
        then
            VALUE="${BASH_REMATCH[1]}"
            VALUE="${VALUE%$'\r'}"

            if [[ "${VALUE}" =~ ^\"([^\"]*)\"$ ]]
            then
                VALUE="${BASH_REMATCH[1]}"
            elif [[ "${VALUE}" =~ ^\'([^\']*)\'$ ]]
            then
                VALUE="${BASH_REMATCH[1]}"
            fi

            [[ "${VALUE}" =~ ^[A-Za-z0-9_.@-]+$ ]] || {
                steam_auth_error "DSM_STEAM_USER inválido em ${CONF}"
                return 1
            }

            printf '%s\n' "${VALUE}"
            return 0
        fi
    done < "${CONF}"

    steam_auth_error "Usuário Steam não configurado em ${CONF}"
    return 1
}

steam_auth_runtime_context()
{
    local ROOT="${1:-/opt/dsm}"
    local ROLE="${2:-}"
    local SERVICE=""
    local RUNTIME_USER=""
    local RUNTIME_HOME=""
    local STATE_DIR=""

    case "${ROLE}" in
        hybrid)
            SERVICE="dsm-dashboard-worker.service"
            RUNTIME_HOME="${ROOT}"
            STATE_DIR="${ROOT}/runtime/hybrid-agent-state"
            ;;
        agent)
            SERVICE="capivara-agent.service"
            RUNTIME_HOME="/var/lib/capivara-agent"
            STATE_DIR="/var/lib/capivara-agent"
            ;;
        *)
            steam_auth_error "cap steam auth requer role agent ou hybrid (detectada: ${ROLE:-unknown})"
            return 1
            ;;
    esac

    if command -v systemctl >/dev/null 2>&1
    then
        RUNTIME_USER="$(systemctl show "${SERVICE}" -p User --value 2>/dev/null || true)"
    fi

    if [[ -z "${RUNTIME_USER}" && "${ROLE}" == "hybrid" ]]
    then
        RUNTIME_USER="$(stat -c '%U' "${ROOT}" 2>/dev/null || true)"
    fi

    [[ -n "${RUNTIME_USER}" && "${RUNTIME_USER}" != "root" ]] || {
        steam_auth_error "Não foi possível determinar o usuário do runtime pelo serviço ${SERVICE}"
        return 1
    }

    printf '%s\n%s\n%s\n%s\n' "${SERVICE}" "${RUNTIME_USER}" "${RUNTIME_HOME}" "${STATE_DIR}"
}

steam_auth_exec_as_runtime()
{
    local RUNTIME_USER="$1"
    local RUNTIME_HOME="$2"
    local STATE_DIR="$3"
    shift 3

    if [[ "$(id -un)" == "${RUNTIME_USER}" ]]
    then
        env \
            HOME="${RUNTIME_HOME}" \
            CAPIVARA_STEAM_HOME="${RUNTIME_HOME}" \
            CAPIVARA_AGENT_STATE_DIR="${STATE_DIR}" \
            "$@"
        return $?
    fi

    if [[ "${EUID}" -ne 0 ]]
    then
        steam_auth_error "Execute 'sudo cap steam auth' para autenticar como ${RUNTIME_USER}."
        return 1
    fi

    command -v sudo >/dev/null 2>&1 || {
        steam_auth_error "sudo não está disponível para trocar para o usuário ${RUNTIME_USER}."
        return 1
    }

    sudo -u "${RUNTIME_USER}" env \
        HOME="${RUNTIME_HOME}" \
        CAPIVARA_STEAM_HOME="${RUNTIME_HOME}" \
        CAPIVARA_AGENT_STATE_DIR="${STATE_DIR}" \
        "$@"
}

steam_auth_resolve_runtime_steamcmd()
{
    local ROOT="$1"
    local RUNTIME_USER="$2"
    local RUNTIME_HOME="$3"
    local STATE_DIR="$4"
    local RUNTIME_DIR="${ROOT}/agents/linux/runtime"
    local RESULT=""

    [[ -f "${RUNTIME_DIR}/game_data_executor.py" ]] || {
        steam_auth_error "Runtime Linux do Agent não encontrado: ${RUNTIME_DIR}"
        return 1
    }

    RESULT="$(
        steam_auth_exec_as_runtime \
            "${RUNTIME_USER}" "${RUNTIME_HOME}" "${STATE_DIR}" \
            env PYTHONPATH="${RUNTIME_DIR}" \
            python3 -c 'from game_data_executor import _steamcmd; print(_steamcmd())'
    )" || return 1

    RESULT="$(printf '%s\n' "${RESULT}" | tail -n 1)"
    [[ -n "${RESULT}" ]] || {
        steam_auth_error "SteamCMD do runtime não pôde ser resolvido."
        return 1
    }

    printf '%s\n' "${RESULT}"
}

steam_auth_run()
{
    local ROOT="${1:-/opt/dsm}"
    local ROLE="${2:-}"
    local STEAM_USER=""
    local SERVICE=""
    local RUNTIME_USER=""
    local RUNTIME_HOME=""
    local STATE_DIR=""
    local STEAMCMD=""
    local CONTEXT=""

    [[ -t 0 && -t 1 ]] || {
        steam_auth_error "Autenticação Steam requer um terminal interativo."
        return 1
    }

    STEAM_USER="$(steam_auth_read_user "${ROOT}")" || return 1
    CONTEXT="$(steam_auth_runtime_context "${ROOT}" "${ROLE}")" || return 1

    SERVICE="$(printf '%s\n' "${CONTEXT}" | sed -n '1p')"
    RUNTIME_USER="$(printf '%s\n' "${CONTEXT}" | sed -n '2p')"
    RUNTIME_HOME="$(printf '%s\n' "${CONTEXT}" | sed -n '3p')"
    STATE_DIR="$(printf '%s\n' "${CONTEXT}" | sed -n '4p')"

    STEAMCMD="$(
        steam_auth_resolve_runtime_steamcmd \
            "${ROOT}" "${RUNTIME_USER}" "${RUNTIME_HOME}" "${STATE_DIR}"
    )" || return 1

    echo
    echo "============================================"
    echo " Capivara - Steam Authentication"
    echo "============================================"
    echo
    echo "Usuário Steam : ${STEAM_USER}"
    echo "Runtime user  : ${RUNTIME_USER}"
    echo "Runtime HOME  : ${RUNTIME_HOME}"
    echo "Serviço       : ${SERVICE}"
    echo "SteamCMD      : ${STEAMCMD}"
    echo
    echo "A senha e o Steam Guard serão solicitados diretamente pelo SteamCMD."
    echo "O Capivara não armazena essas credenciais."
    echo

    steam_auth_exec_as_runtime \
        "${RUNTIME_USER}" "${RUNTIME_HOME}" "${STATE_DIR}" \
        "${STEAMCMD}" +login "${STEAM_USER}" +quit
    local STATUS=$?

    if (( STATUS != 0 ))
    then
        steam_auth_error "Falha na autenticação Steam."
        return "${STATUS}"
    fi

    # Prove that Steam persisted a reusable login token in the exact runtime
    # context used by unattended game/Workshop installs. No password or Guard
    # code is supplied on this second invocation.
    local PROBE_STATUS=0
    steam_auth_exec_as_runtime \
        "${RUNTIME_USER}" "${RUNTIME_HOME}" "${STATE_DIR}" \
        "${STEAMCMD}" +login "${STEAM_USER}" +quit \
        </dev/null >/dev/null 2>&1 || PROBE_STATUS=$?

    if (( PROBE_STATUS != 0 ))
    then
        steam_auth_error "A Steam aceitou o login interativo, mas não persistiu uma sessão reutilizável."
        steam_auth_error "Repita 'sudo cap steam auth' e confirme Steam Guard/lembrar sessão quando solicitado."
        return "${PROBE_STATUS}"
    fi

    echo "[DSM][STEAM] Autenticação Steam concluída no contexto persistente do Agent."
    echo "[DSM][STEAM] Sessão não interativa validada e pronta para instalações Steam/Workshop."
    return 0
}
