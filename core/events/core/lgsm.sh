#!/usr/bin/env bash
# =============================================================
# DSM
# core/lgsm.sh
#
# Camada de integração LinuxGSM
#
# Responsável por fornecer:
#   - Instância LinuxGSM
#   - Diretórios
#   - PID
#   - Status
#   - Uptime
#   - Mods
#   - Execução de comandos
#
# =============================================================

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
CONFIG="${DSM_ROOT}/config/dsm.conf"

# -------------------------------------------------------------
# Carregar configuração DSM
# -------------------------------------------------------------
if [[ -f "$CONFIG" ]]
then
    source "$CONFIG"
fi

# -------------------------------------------------------------
# Configuração LinuxGSM vinda do DSM
# -------------------------------------------------------------
LGSM_USER="${LGSM_USER:-${DSM_USER:-}}"
LGSM_INSTANCE="${LGSM_INSTANCE:-${INSTANCE_NAME:-}}"
LGSM_DIR="${LGSM_DIR:-${LINUXGSM_PATH:-}}"
SERVERFILES_DIR="${SERVERFILES_PATH:-${LGSM_DIR}/serverfiles}"

# -------------------------------------------------------------
# Validação
# -------------------------------------------------------------
lgsm_validate()
{
    [[ -n "$LGSM_USER" ]] || {
        echo "LGSM_USER não configurado"
        return 1
    }

    [[ -n "$LGSM_INSTANCE" ]] || {
        echo "LGSM_INSTANCE não configurado"
        return 1
    }

    [[ -n "$LGSM_DIR" ]] || {
        echo "LGSM_DIR não configurado"
        return 1
    }
}

# -------------------------------------------------------------
# Caminho do script LinuxGSM
# -------------------------------------------------------------
lgsm_script()
{
    echo "${LGSM_DIR}/${LGSM_INSTANCE}"
}

# -------------------------------------------------------------
# Diretório serverfiles
# -------------------------------------------------------------
lgsm_serverfiles()
{
    echo "$SERVERFILES_DIR"
}

# -------------------------------------------------------------
# Diretório dos Mods
# -------------------------------------------------------------
lgsm_mods_dir()
{
    echo "$(lgsm_serverfiles)/mods"
}

# -------------------------------------------------------------
# Diretório de logs LinuxGSM
# -------------------------------------------------------------
lgsm_log_dir()
{
    echo "${LGSM_DIR}/log"
}

# -------------------------------------------------------------
# PID LinuxGSM
#
# Usa arquivo PID gerado pelo LinuxGSM
# Não usa pgrep
# -------------------------------------------------------------
lgsm_pid()
{
    local PID_FILE
    PID_FILE="$(lgsm_serverfiles)/serverfiles.pid"

    if [[ -f "$PID_FILE" ]]
    then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

# -------------------------------------------------------------
# Status
# -------------------------------------------------------------
lgsm_status()
{
    local PID
    PID=$(lgsm_pid)

    if [[ -n "$PID" ]] &&
       kill -0 "$PID" 2>/dev/null
    then
        echo "online"
    else
        echo "offline"
    fi
}

# -------------------------------------------------------------
# Uptime
# -------------------------------------------------------------
lgsm_uptime()
{
    local PID
    PID=$(lgsm_pid)

    [[ -z "$PID" ]] && return

    ps -p "$PID" \
    -o etime= \
    | xargs
}

# -------------------------------------------------------------
# Nome da instância
# -------------------------------------------------------------
lgsm_instance()
{
    echo "$LGSM_INSTANCE"
}

# -------------------------------------------------------------
# Nome do servidor
# -------------------------------------------------------------
lgsm_name()
{
    echo "$LGSM_INSTANCE"
}

# -------------------------------------------------------------
# Executar comando LinuxGSM
# -------------------------------------------------------------
lgsm_exec()
{
    local CMD="$1"

    sudo -u "$LGSM_USER" \
    "$(lgsm_script)" \
    "$CMD"
}
