#!/bin/bash
# =============================================================
# core/logger.sh - MÓDULO 01 (CORE)
#
# Sistema de Log do DSM
# DSM Logging System
#
# Responsável por:
# Responsible for:
# - saída colorida | colored output
# - log estruturado | structured log
# - escrita segura (flock) | safe writing (flock)
# - níveis de log | log levels
# - rotação de logs | log rotation
#
# =============================================================

# =============================================================
# Cores
# Colors
# =============================================================
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_CYAN='\033[0;36m'
C_MAGENTA='\033[0;35m'
C_BOLD='\033[1m'

# =============================================================
# Diretórios
# Directories
# =============================================================
DSM_LOG_DIR="${DSM_ROOT}/logs"
DSM_LOG_FILE="${DSM_LOG_DIR}/dsm.log"

: "${LOG_MODULE:=dsm}"

# =============================================================
# Inicialização
# Initialization
# =============================================================
log_init()
{
    mkdir -p "$DSM_LOG_DIR"
    touch "$DSM_LOG_FILE"
}

# =============================================================
# Timestamp ISO8601
# =============================================================
log_timestamp()
{
    date +"%Y-%m-%dT%H:%M:%S%z"
}

# =============================================================
# Escrita segura
# Safe writing
#
# Formato: | Format:
#
# [timestamp] [LEVEL] [module] mensagem
# [timestamp] [LEVEL] [module] message
#
# =============================================================
_log_write()
{
    local level="$1"
    local module="$2"
    shift 2

    local ts
    ts="$(log_timestamp)"

    {
        flock -x 200
        printf "[%s] [%s] [%s] %s\n" \
                "$ts" \
                "$level" \
                "$module" \
                "$*" >&200

        } 200>>"$DSM_LOG_FILE"
}

# =============================================================
# Saída colorida
# Colored output
# =============================================================
log_info()
{
    _log_write INFO "$LOG_MODULE" "$@"

        if [[ "${LOG_CONSOLE:-1}" -eq 1 ]]
        then
            echo -e "$*"
        fi
}

log_ok()
{
    _log_write OK "$LOG_MODULE" "$@"
    echo -e "${C_GREEN}[OK]${C_RESET} $*"
}

log_warn()
{
    _log_write WARNING "$LOG_MODULE" "$@"
    echo -e "${C_YELLOW}[WARNING]${C_RESET} $*"
}

log_notice()
{
    _log_write NOTICE "$LOG_MODULE" "$@"
    echo -e "${C_BLUE}[NOTICE]${C_RESET} $*"
}

log_error()
{
    _log_write ERROR "$LOG_MODULE" "$@"
    echo -e "${C_RED}[ERROR]${C_RESET} $*"
}

log_critical()
{
    _log_write CRITICAL "$LOG_MODULE" "$@"
    echo -e "${C_BOLD}${C_RED}[CRITICAL]${C_RESET} $*"
}

log_debug()
{
    [ "${DSM_DEBUG:-0}" = "1" ] || return 0

    _log_write DEBUG "$LOG_MODULE" "$@"
    echo -e "${C_MAGENTA}[DEBUG]${C_RESET} $*"
}

log_success()
{
    _log_write SUCCESS "$LOG_MODULE" "$@"
    echo -e "${C_GREEN}[OK]${C_RESET} $*"
}

# =============================================================
# Log JSON
#
# Exemplo: | Example:
#
# log_json '{"event":"server_down","pid":1234}'
#
# =============================================================
log_json()
{
    local json="$1"
    _log_write JSON "$LOG_MODULE" "$json"
}

# =============================================================
# Cabeçalhos
# Headers
# =============================================================
section()
{
    echo
    echo -e "${C_BOLD}${C_BLUE}== $* ==${C_RESET}"
}

line()
{
    printf '%*s\n' 60 '' | tr ' ' '-'
}

# =============================================================
# Consulta de logs
# Log query
# =============================================================
log_tail()
{
    local lines="${1:-50}"
    tail -n "$lines" "$DSM_LOG_FILE" 2>/dev/null
}

# =============================================================
# Rotação de logs
# Log rotation
#
# Mantém: | Maintains:
#
# dsm.log
# dsm.log.1
# dsm.log.2.gz
# dsm.log.3.gz
#
# =============================================================
log_rotate()
{
    local max_size_mb="${1:-20}"

    [ -f "$DSM_LOG_FILE" ] || return 0

    local size
    size=$(( $(stat -c%s "$DSM_LOG_FILE" 2>/dev/null) / 1024 / 1024 ))

    [ "$size" -lt "$max_size_mb" ] && return 0

    rm -f "$DSM_LOG_FILE.3.gz"

    [ -f "$DSM_LOG_FILE.2.gz" ] && \
        mv "$DSM_LOG_FILE.2.gz" "$DSM_LOG_FILE.3.gz"

    [ -f "$DSM_LOG_FILE.1.gz" ] && \
        mv "$DSM_LOG_FILE.1.gz" "$DSM_LOG_FILE.2.gz"

    [ -f "$DSM_LOG_FILE.1" ] && {
        gzip -f "$DSM_LOG_FILE.1"
        mv "$DSM_LOG_FILE.1.gz" "$DSM_LOG_FILE.1.gz"
    }

    mv "$DSM_LOG_FILE" "$DSM_LOG_FILE.1"
    touch "$DSM_LOG_FILE"
}

# =============================================================
# Limpeza automática
# Automatic cleanup
#
# Remove logs compactados antigos
# Removes old compressed logs
# =============================================================
log_cleanup()
{
    local days="${1:-30}"

    find "$DSM_LOG_DIR" \
        -name "*.gz" \
        -mtime +"$days" \
        -delete 2>/dev/null
}
