#!/usr/bin/env bash
#==============================================================================
# DayZ Server Manager (DSM)
# dashboard/api/console.sh
# Console Web API
# Versão : 3.0.0
#==============================================================================

set -Eeuo pipefail

#==============================================================================
# DSM
#==============================================================================
readonly DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
if [[ -s "${DSM_ROOT}/version" ]]
then
    DSM_VERSION=$(tr -d '\r\n' <"${DSM_ROOT}/version")
else
    DSM_VERSION="unknown"
fi
readonly DSM_VERSION
readonly API_DIR="${DSM_ROOT}/dashboard/api"
readonly LOG_DIR="${DSM_ROOT}/logs"
readonly STATE_DIR="${DSM_ROOT}/dashboard/state"
readonly HISTORY_FILE="${STATE_DIR}/console_history.json"
readonly AUDIT_LOG="${LOG_DIR}/console.log"
readonly BIN_DSM="/usr/local/bin/dsm"
readonly USERNAME="${DSM_USER:-unknown}"
readonly ROLE="${DSM_ROLE:-unknown}"

#==============================================================================
# Timestamp
#==============================================================================
timestamp() {
    date +"%Y-%m-%d %H:%M:%S"
}

#==============================================================================
# Logger
#==============================================================================
log_info() {
    printf "[%s] [INFO] %s\n" "$(timestamp)" "$1" >> "${AUDIT_LOG}"
}

#==============================================================================
# JSON Helpers
#==============================================================================
json_ok() {
cat <<EOF
{
    "success": true,
    "command": "${COMMAND}",
    "output": ${1:-"{}"}
}
EOF
}

json_error() {
cat <<EOF
{
    "success": false,
    "command": "${COMMAND}",
    "error": "$1"
}
EOF
exit 1
}

#==============================================================================
# Dependências
#==============================================================================
require_binary() {
    if [[ ! -x "${BIN_DSM}" ]]
    then
        json_error "CLI do DSM não encontrada."
    fi
}

#==============================================================================
# RBAC
#==============================================================================
require_admin() {
    if [[ "${ROLE}" != "admin" ]]
    then
        json_error "Console disponível apenas para administradores."
    fi
}

#==============================================================================
# Diretórios
#==============================================================================
prepare_environment() {
    mkdir -p "${LOG_DIR}"
    mkdir -p "${STATE_DIR}"
    touch "${AUDIT_LOG}"
}

#==============================================================================
# Comandos permitidos
#==============================================================================
declare -A COMMANDS
COMMANDS["status"]="server"
COMMANDS["start"]="server"
COMMANDS["stop"]="server"
COMMANDS["restart"]="server"
COMMANDS["doctor"]="doctor"
COMMANDS["monitor"]="monitor"
COMMANDS["metrics"]="metrics"
COMMANDS["mods"]="mods"
COMMANDS["backup"]="backup"
COMMANDS["scheduler"]="scheduler"
COMMANDS["events"]="events"
COMMANDS["alerts"]="alerts"
COMMANDS["notifications"]="notifications"
COMMANDS["discord"]="discord"

#==============================================================================
# Ações permitidas por módulo
#==============================================================================
declare -A ALLOWED_ACTIONS
ALLOWED_ACTIONS["server"]="status start stop restart"
ALLOWED_ACTIONS["doctor"]="quick full"
ALLOWED_ACTIONS["monitor"]="status"
ALLOWED_ACTIONS["metrics"]="status"
ALLOWED_ACTIONS["mods"]="status verify install update remove rollback"
ALLOWED_ACTIONS["backup"]="status create restore delete rotate"
ALLOWED_ACTIONS["scheduler"]="status list history run-once enable disable daemon"
ALLOWED_ACTIONS["events"]="list"
ALLOWED_ACTIONS["alerts"]="list"
ALLOWED_ACTIONS["notifications"]="list history clear"
ALLOWED_ACTIONS["discord"]="status reload send-test"

#==============================================================================
# Variáveis Globais
#==============================================================================
COMMAND=""
MODULE=""
ACTION=""
ARGS=()
OUTPUT=""
EXIT_CODE=0

#==============================================================================
# Utilitários
#==============================================================================
command_exists() {
    [[ -n "${COMMANDS[$1]:-}" ]]
}

action_allowed() {
    local module="$1"
    local action="$2"

    for item in ${ALLOWED_ACTIONS[$module]}
    do
        if [[ "$item" == "$action" ]]
        then
            return 0
        fi
    done
    return 1
}

#==============================================================================
# Parser
#==============================================================================
parse_arguments() {
    if (( $# == 0 ))
    then
        json_error "Nenhum comando informado."
    fi

    COMMAND="$1"
    shift || true
    MODULE="${COMMANDS[$COMMAND]:-}"

    if [[ -z "${MODULE}" ]]
    then
        json_error "Comando não permitido."
    fi

    if (( $# == 0 ))
    then
        case "${MODULE}" in
            server) ACTION="${COMMAND}" ;;
            *) ACTION="status" ;;
        esac
    else
        ACTION="$1"
        shift || true
    fi
    ARGS=("$@")
}

#==============================================================================
# Script correspondente
#==============================================================================
script_path() {
    printf "%s/%s.sh" "${API_DIR}" "${MODULE}"
}

#==============================================================================
# Execução
#==============================================================================
execute_api() {
    local script
    script="$(script_path)"

    if [[ ! -f "${script}" ]]
    then
        json_error "API ${MODULE}.sh não encontrada."
    fi

    if [[ ! -x "${script}" ]]
    then
        chmod +x "${script}" 2>/dev/null || true
    fi

    if ! action_allowed "${MODULE}" "${ACTION}"
    then
        json_error "Ação '${ACTION}' não permitida para ${MODULE}."
    fi

    log_info "Usuário=${USERNAME} Módulo=${MODULE} Ação=${ACTION}"

    OUTPUT="$(
        DSM_ROOT="${DSM_ROOT}" \
        DSM_USER="${USERNAME}" \
        DSM_ROLE="${ROLE}" \
        bash "${script}" \
            "${ACTION}" \
            "${ARGS[@]}" \
            2>&1
    )"
    EXIT_CODE=$?
}

#==============================================================================
# Resultado
#==============================================================================
handle_result() {
    if (( EXIT_CODE == 0 ))
    then
        log_info "Sucesso ${MODULE}/${ACTION}"
    else
        log_error "Falha ${MODULE}/${ACTION}"
    fi
}

#==============================================================================
# Sanitização
#==============================================================================
sanitize_output() {
    OUTPUT="$(printf "%s" "${OUTPUT}" | tr -d '\r')"
}

#==============================================================================
# Escape JSON
#==============================================================================
json_escape() {
    python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

#==============================================================================
# Resposta
#==============================================================================
reply_json() {
    sanitize_output
    local escaped
    escaped="$(printf "%s" "${OUTPUT}" | json_escape)"

    cat <<EOF
{
    "success": $([[ ${EXIT_CODE} -eq 0 ]] && echo true || echo false),
    "module": "${MODULE}",
    "command": "${COMMAND}",
    "action": "${ACTION}",
    "user": "${USERNAME}",
    "exit_code": ${EXIT_CODE},
    "timestamp": "$(timestamp)",
    "output": ${escaped}
}
EOF
}

#==============================================================================
# Wrapper
#==============================================================================
run_command() {
    parse_arguments "$@"
    execute_api
    handle_result
    reply_json
}

#==============================================================================
# Histórico persistente
#==============================================================================
readonly NOTIFICATION_API="${API_DIR}/notifications.sh"
readonly DISCORD_API="${API_DIR}/discord.sh"
readonly MAX_HISTORY=200

escape_json() {
    printf '%s' "$1" | python3 -c 'import json; import sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

initialize_history() {
    if [[ ! -f "${HISTORY_FILE}" ]]
    then
cat > "${HISTORY_FILE}" <<EOF
[]
EOF
    fi
}

save_history() {
    initialize_history
    local result
    if (( EXIT_CODE == 0 ))
    then
        result="success"
    else
        result="error"
    fi

    python3 <<EOF
import json
import pathlib
history = pathlib.Path("${HISTORY_FILE}")
data = json.loads(history.read_text())
data.append({
    "timestamp":"$(timestamp)",
    "user":"${USERNAME}",
    "role":"${ROLE}",
    "module":"${MODULE}",
    "command":"${COMMAND}",
    "action":"${ACTION}",
    "exit_code":${EXIT_CODE},
    "result":"${result}"
})
data=data[-${MAX_HISTORY}:]
history.write_text(json.dumps(data, indent=4, ensure_ascii=False))
EOF
}

audit_command() {
    local status="OK"
    if (( EXIT_CODE != 0 ))
    then
        status="ERROR"
    fi
    printf "%s | %-12s | %-10s | %-14s | %-12s | %s\n" \
        "$(timestamp)" \
        "${USERNAME}" \
        "${MODULE}" \
        "${ACTION}" \
        "${status}" \
        "${COMMAND}" \
        >> "${AUDIT_LOG}"
}

send_notification() {
    local level="$1"
    local title="$2"
    local message="$3"
    if [[ ! -x "${NOTIFICATION_API}" ]]
    then
        return
    fi
    "${NOTIFICATION_API}" push "${level}" "${title}" "${message}" >/dev/null 2>&1 || true
}

notify_action() {
    (( EXIT_CODE != 0 )) && return
    case "${MODULE}/${ACTION}" in
        server/start) send_notification success "Servidor iniciado" "${USERNAME} iniciou o servidor" ;;
        server/stop) send_notification warning "Servidor parado" "${USERNAME} parou o servidor" ;;
        server/restart) send_notification warning "Servidor reiniciado" "${USERNAME} reiniciou o servidor" ;;
        backup/create) send_notification success "Backup criado" "${USERNAME} executou um backup" ;;
        doctor/full) send_notification info "Doctor executado" "${USERNAME} executou o diagnóstico completo" ;;
        mods/update) send_notification info "Mods atualizados" "${USERNAME} atualizou os mods" ;;
        scheduler/run-once) send_notification info "Scheduler" "Job executado manualmente por ${USERNAME}" ;;
    esac
}

dispatch_discord() {
    [[ ! -x "${DISCORD_API}" ]] && return
    "${DISCORD_API}" worker >/dev/null 2>&1 || true
}

post_execution() {
    audit_command
    save_history
    notify_action
    dispatch_discord
}

console_statistics() {
    local total
    total=$(python3 <<EOF
import json
from pathlib import Path
f = Path("${HISTORY_FILE}")
if not f.exists():
    print(0)
else:
    print(len(json.loads(f.read_text())))
EOF
    )
    log_info "Histórico=${total} registros"
}

#==============================================================================
# Dispatcher principal
#==============================================================================
readonly MAX_ARGUMENTS=10
readonly MAX_ARGUMENT_LENGTH=128
readonly COMMAND_TIMEOUT=300

contains_forbidden_chars() {
    local value="$1"
    local forbidden=(';' '&&' '||' '|' '`' '$(' '<' '>' '>>' '<<' '&')
    local item
    for item in "${forbidden[@]}"
    do
        if [[ "$value" == *"$item"* ]]
        then
            return 0
        fi
    done
    return 1
}

validate_arguments() {
    if (( ${#ARGS[@]} > MAX_ARGUMENTS ))
    then
        json_error "Quantidade de argumentos excedida."
    fi

    local arg
    for arg in "${ARGS[@]}"
    do
        if (( ${#arg} > MAX_ARGUMENT_LENGTH ))
        then
            json_error "Argumento muito grande."
        fi
        if contains_forbidden_chars "$arg"
        then
            json_error "Argumento contém caracteres proibidos."
        fi
    done
}

execute_with_timeout() {
    local script
    script="$(script_path)"
    OUTPUT="$(
        timeout "${COMMAND_TIMEOUT}" \
        env \
            DSM_ROOT="${DSM_ROOT}" \
            DSM_USER="${USERNAME}" \
            DSM_ROLE="${ROLE}" \
        bash "${script}" \
            "${ACTION}" \
            "${ARGS[@]}" \
            2>&1
    )"
    EXIT_CODE=$?
    if [[ "${EXIT_CODE}" == "124" ]]
    then
        json_error "Tempo limite excedido."
    fi
}

dispatch() {
    require_binary
    require_admin
    prepare_environment
    parse_arguments "$@"
    validate_arguments
    execute_with_timeout
    handle_result
    post_execution
    reply_json
}

panic() {
    local line="$1"
    local code="$2"
    log_error "Falha inesperada linha=${line} código=${code}"
cat <<EOF
{
    "success": false,
    "error": "Erro interno do Console DSM.",
    "line": ${line},
    "exit_code": ${code}
}
EOF
    exit "${code}"
}

trap 'panic ${LINENO} $?' ERR

show_help() {
cat <<EOF
DSM Console API
Uso: console.sh <comando> [ação] [argumentos]
Exemplos: console.sh status, start, stop, restart, doctor full, backup create, mods verify, scheduler status
EOF
}

show_version() {
cat <<EOF
DSM Console API
Versão: ${DSM_VERSION}
EOF
}

self_test() {
    prepare_environment
    require_binary
    echo "Console DSM"
    echo "DSM_ROOT: ${DSM_ROOT}"
    echo "Usuário: ${USERNAME}"
    echo "Perfil: ${ROLE}"
    echo "API: ${API_DIR}"
    echo "Histórico: ${HISTORY_FILE}"
    echo "Log: ${AUDIT_LOG}"
    echo "OK"
}

#==============================================================================
# Bootstrap & Main
#==============================================================================
bootstrap() {
    prepare_environment
    initialize_history
    require_binary
    log_info "Console DSM inicializado."
}

show_banner() {
cat <<EOF
=========================================================
               DSM Console API
=========================================================
Versão      : ${DSM_VERSION}
Usuário     : ${USERNAME}
Perfil      : ${ROLE}
DSM_ROOT    : ${DSM_ROOT}
=========================================================
EOF
}

health_check() {
    local ok=true
    [[ -d "${DSM_ROOT}" ]] || ok=false
    [[ -d "${API_DIR}" ]] || ok=false
    [[ -d "${STATE_DIR}" ]] || ok=false
    cat <<EOF
{
    "success": ${ok},
    "version": "${DSM_VERSION}",
    "user": "${USERNAME}",
    "role": "${ROLE}",
    "paths": {
        "dsm_root": "${DSM_ROOT}",
        "api": "${API_DIR}",
        "state": "${STATE_DIR}",
        "history": "${HISTORY_FILE}",
        "audit_log": "${AUDIT_LOG}"
    }
}
EOF
}

main() {
    bootstrap
    case "${1:-}" in
        "") json_error "Nenhum comando informado." ;;
        help|-h|--help) show_help; exit 0 ;;
        version|-v|--version) show_version; exit 0 ;;
        banner) show_banner; exit 0 ;;
        self-test) self_test; exit 0 ;;
        health) health_check; exit 0 ;;
        *) dispatch "$@" ;;
    esac
}

finish() {
    console_statistics
    log_info "Console encerrado."
}

cleanup() {
    finish
}

trap cleanup EXIT
main "$@"
