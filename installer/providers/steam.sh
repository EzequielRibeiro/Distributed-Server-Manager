#!/usr/bin/env bash

# =============================================================
# Capivara Distributed Server Manager
# Installation Provider - Steam
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

STEAMCMD_INSTALLER="${DSM_ROOT}/tools/install_steamcmd.sh"
STEAMCMD_ROOT="${DSM_ROOT}/tools/steamcmd"
STEAMCMD_BIN="${STEAMCMD_ROOT}/steamcmd.sh"
STEAMCMD_PROGRESS_LOG="${DSM_ROOT}/logs/steamcmd-progress.log"

steam_log()
{
    echo "[DSM][STEAM] $*"
}

steam_error()
{
    echo "[DSM][STEAM][ERRO] $*" >&2
}

steam_progress_publish()
{
    local STEAM_PERCENT="${1:-0}"
    local WHOLE
    local CAP_PROGRESS

    WHOLE="${STEAM_PERCENT%%.*}"
    [[ "${WHOLE}" =~ ^[0-9]+$ ]] || return 0

    (( WHOLE < 0 )) && WHOLE=0
    (( WHOLE > 100 )) && WHOLE=100

    CAP_PROGRESS=$((25 + (WHOLE * 50 / 100)))

    if declare -F install_operation_progress_safe >/dev/null 2>&1
    then
        install_operation_progress_safe \
            "downloading" \
            "${CAP_PROGRESS}" \
            "SteamCMD: ${STEAM_PERCENT}%"
    fi
}

steam_progress_parse_line()
{
    local LINE="${1:-}"
    local PERCENT=""

    LINE="$(printf '%s' "${LINE}" | sed -E $'s/\x1B\\[[0-9;?]*[ -\/]*[@-~]//g')"

    if [[ "${LINE}" =~ [Pp]rogress[[:space:]]*:[[:space:]]*([0-9]+([.][0-9]+)?) ]]
    then
        PERCENT="${BASH_REMATCH[1]}"
        steam_progress_publish "${PERCENT}"
        return 0
    fi

    if [[ "${LINE}" =~ ([0-9]+([.][0-9]+)?)[[:space:]]*% ]]
    then
        PERCENT="${BASH_REMATCH[1]}"
        steam_progress_publish "${PERCENT}"
    fi

    return 0
}

steamcmd_build_command()
{
    local CMD
    local ARG

    printf -v CMD '%q' "${STEAMCMD_BIN}"

    for ARG in "$@"
    do
        printf -v CMD '%s %q' "${CMD}" "${ARG}"
    done

    printf '%s\n' "${CMD}"
}

steamcmd_run_with_progress()
{
    local STATUS=0
    local LINE
    local CMD

    mkdir -p "$(dirname "${STEAMCMD_PROGRESS_LOG}")"
    : > "${STEAMCMD_PROGRESS_LOG}"

    CMD="$(steamcmd_build_command "$@")"

    # SteamCMD pode reduzir/suprimir progresso quando stdout não é TTY.
    # `script` cria um pseudo-terminal e mantém a saída interativa.
    if command -v script >/dev/null 2>&1
    then
        script -qefc "${CMD}" /dev/null 2>&1 |
            tr '\r' '\n' |
            while IFS= read -r LINE || [[ -n "${LINE}" ]]
            do
                [[ -n "${LINE}" ]] || continue
                printf '%s\n' "${LINE}"
                printf '%s\n' "${LINE}" >> "${STEAMCMD_PROGRESS_LOG}"
                steam_progress_parse_line "${LINE}"
            done

        STATUS=${PIPESTATUS[0]}
    else
        steam_log "Aviso: comando 'script' não disponível; usando captura sem pseudo-TTY."

        "${STEAMCMD_BIN}" "$@" 2>&1 |
            tr '\r' '\n' |
            while IFS= read -r LINE || [[ -n "${LINE}" ]]
            do
                [[ -n "${LINE}" ]] || continue
                printf '%s\n' "${LINE}"
                printf '%s\n' "${LINE}" >> "${STEAMCMD_PROGRESS_LOG}"
                steam_progress_parse_line "${LINE}"
            done

        STATUS=${PIPESTATUS[0]}
    fi

    return "${STATUS}"
}

steam_provider_ensure()
{
    if [[ -x "${STEAMCMD_BIN}" ]]
    then
        steam_log "SteamCMD disponível:"
        steam_log "${STEAMCMD_BIN}"
        return 0
    fi

    steam_log "SteamCMD não encontrado."

    if [[ ! -x "${STEAMCMD_INSTALLER}" ]]
    then
        steam_error "Instalador do SteamCMD não encontrado:"
        steam_error "${STEAMCMD_INSTALLER}"
        return 1
    fi

    steam_log "Instalando SteamCMD..."

    if ! "${STEAMCMD_INSTALLER}"
    then
        steam_error "Falha ao instalar SteamCMD."
        return 1
    fi

    [[ -x "${STEAMCMD_BIN}" ]] || return 1
    return 0
}

steam_provider_validate()
{
    local INTERNAL_BIN=""

    steam_provider_ensure || return 1

    if [[ ! -x "${STEAMCMD_BIN}" ]]
    then
        steam_error "Launcher SteamCMD não é executável:"
        steam_error "${STEAMCMD_BIN}"
        return 1
    fi

    if [[ -f "${STEAMCMD_ROOT}/linux32/steamcmd" ]]
    then
        INTERNAL_BIN="${STEAMCMD_ROOT}/linux32/steamcmd"
    elif [[ -f "${STEAMCMD_ROOT}/linux64/steamcmd" ]]
    then
        INTERNAL_BIN="${STEAMCMD_ROOT}/linux64/steamcmd"
    else
        steam_error "Binário interno do SteamCMD não encontrado."
        return 1
    fi

    if [[ ! -x "${INTERNAL_BIN}" ]]
    then
        steam_error "Binário interno do SteamCMD não é executável:"
        steam_error "${INTERNAL_BIN}"
        return 1
    fi

    return 0
}

steam_manifest_path()
{
    local INSTALL_PATH="$1"
    local APP_ID="$2"
    echo "${INSTALL_PATH}/steamapps/appmanifest_${APP_ID}.acf"
}

steam_manifest_exists()
{
    local INSTALL_PATH="$1"
    local APP_ID="$2"
    [[ -f "$(steam_manifest_path "${INSTALL_PATH}" "${APP_ID}")" ]]
}

steam_buildid()
{
    local INSTALL_PATH="$1"
    local APP_ID="$2"
    local MANIFEST
    local BUILD_ID

    MANIFEST="$(steam_manifest_path "${INSTALL_PATH}" "${APP_ID}")"
    [[ -f "${MANIFEST}" ]] || return 1

    BUILD_ID="$(awk -F'"' '/"buildid"/ { print $4; exit }' "${MANIFEST}")"
    [[ -n "${BUILD_ID}" ]] || return 1
    echo "${BUILD_ID}"
}

steam_provider_install_anonymous()
{
    local APP_ID="$1"
    local INSTALL_PATH="$2"

    steam_log "Instalação Steam anônima"
    steam_log "AppID   : ${APP_ID}"
    steam_log "Destino : ${INSTALL_PATH}"

    mkdir -p "${INSTALL_PATH}"

    steamcmd_run_with_progress \
        +force_install_dir "${INSTALL_PATH}" \
        +login anonymous \
        +app_update "${APP_ID}" validate \
        +quit
}

steam_provider_authenticate()
{
    local STEAM_USER="${1:-}"
    local STATUS=0

    if [[ -z "${STEAM_USER}" || "${STEAM_USER}" == "anonymous" ]]
    then
        steam_error "Usuário Steam não informado."
        return 1
    fi

    steam_provider_validate || return 1

    if [[ ! -t 0 || ! -t 1 ]]
    then
        steam_error "Autenticação Steam requer um terminal interativo."
        steam_error "Execute esta operação diretamente em um terminal administrativo."
        return 1
    fi

    echo
    echo "============================================"
    echo " Capivara - Steam Authentication"
    echo "============================================"
    echo
    echo "Usuário Steam: ${STEAM_USER}"
    echo
    echo "A senha e o Steam Guard serão solicitados diretamente pelo SteamCMD."
    echo "O Capivara não armazena essas credenciais."
    echo

    "${STEAMCMD_BIN}" \
        +login "${STEAM_USER}" \
        +quit

    STATUS=$?

    if (( STATUS != 0 ))
    then
        steam_error "Falha na autenticação Steam."
        return "${STATUS}"
    fi

    steam_log "Autenticação Steam concluída."
    return 0
}

steam_provider_install_authenticated()
{
    local APP_ID="$1"
    local INSTALL_PATH="$2"
    local STEAM_USER="$3"

    [[ -n "${STEAM_USER}" ]] || return 1
    mkdir -p "${INSTALL_PATH}"

    # O provisionamento do Dashboard não possui terminal para responder a
    # senha/Steam Guard. Valide primeiro as credenciais em cache sem pseudo-TTY
    # para que a operação falhe rapidamente e possa orientar o administrador.
    local AUTH_OUTPUT=""
    local AUTH_STATUS=0
    if command -v timeout >/dev/null 2>&1
    then
        AUTH_OUTPUT="$(timeout 60 "${STEAMCMD_BIN}" \
            +login "${STEAM_USER}" +quit </dev/null 2>&1)" || AUTH_STATUS=$?
    else
        AUTH_OUTPUT="$("${STEAMCMD_BIN}" \
            +login "${STEAM_USER}" +quit </dev/null 2>&1)" || AUTH_STATUS=$?
    fi

    if (( AUTH_STATUS != 0 ))
    then
        printf '%s\n' "${AUTH_OUTPUT}"
        steam_error "Autenticação Steam necessária ou expirada."
        steam_error "Execute 'dsm steam auth' no Agent e tente novamente."
        return 42
    fi

    steamcmd_run_with_progress \
        +force_install_dir "${INSTALL_PATH}" \
        +login "${STEAM_USER}" \
        +app_update "${APP_ID}" validate \
        +quit
}

steam_provider_install()
{
    local APP_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local STEAM_USER="${3:-anonymous}"

    [[ -n "${APP_ID}" ]] || { steam_error "AppID não informado."; return 1; }
    [[ -n "${INSTALL_PATH}" ]] || { steam_error "Diretório de instalação não informado."; return 1; }

    steam_provider_validate || return 1

    echo
    echo "============================================"
    echo " Capivara - Steam Provider"
    echo "============================================"
    echo
    echo "AppID   : ${APP_ID}"
    echo "Destino : ${INSTALL_PATH}"
    echo

    if [[ "${STEAM_USER}" == "anonymous" ]]
    then
        steam_provider_install_anonymous "${APP_ID}" "${INSTALL_PATH}" || return 1
    else
        steam_provider_install_authenticated "${APP_ID}" "${INSTALL_PATH}" "${STEAM_USER}" || return 1
    fi

    steam_progress_publish 100
    steam_log "Operação Steam concluída."
    return 0
}

steam_provider_update()
{
    steam_provider_install "$@"
}

steam_provider_verify()
{
    local APP_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local MANIFEST
    local BUILD_ID

    [[ -n "${APP_ID}" ]] || return 1
    [[ -n "${INSTALL_PATH}" ]] || return 1

    MANIFEST="$(steam_manifest_path "${INSTALL_PATH}" "${APP_ID}")"
    [[ -f "${MANIFEST}" ]] || return 1

    BUILD_ID="$(steam_buildid "${INSTALL_PATH}" "${APP_ID}" 2>/dev/null || true)"
    [[ -n "${BUILD_ID}" ]] || return 1

    echo "[OK] Steam manifest"
    echo "[OK] BuildID: ${BUILD_ID}"
    return 0
}

steam_provider_info()
{
    local APP_ID="${1:-}"
    local INSTALL_PATH="${2:-}"
    local BUILD_ID=""

    BUILD_ID="$(steam_buildid "${INSTALL_PATH}" "${APP_ID}" 2>/dev/null || true)"
    echo "provider=steam"
    echo "appid=${APP_ID}"
    echo "buildid=${BUILD_ID:-0}"
}

provider_ensure() { steam_provider_ensure; }
provider_install() { steam_provider_install "$@"; }
provider_update() { steam_provider_update "$@"; }
provider_verify() { steam_provider_verify "$@"; }
provider_info() { steam_provider_info "$@"; }
provider_version() { steam_buildid "${2:-}" "${1:-}"; }

export -f steam_log steam_error
export -f steam_progress_publish steam_progress_parse_line
export -f steamcmd_build_command steamcmd_run_with_progress
export -f steam_provider_ensure steam_provider_validate
export -f steam_manifest_path steam_manifest_exists steam_buildid
export -f steam_provider_authenticate
export -f steam_provider_install_anonymous steam_provider_install_authenticated
export -f steam_provider_install steam_provider_update steam_provider_verify steam_provider_info
export -f provider_ensure provider_install provider_update provider_verify provider_info provider_version
