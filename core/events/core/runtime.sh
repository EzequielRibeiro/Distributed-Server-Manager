#!/bin/bash
# =============================================================
# core/runtime.sh - MÓDULO 01 (CORE)
#
# Informações do ambiente de execução do DSM
#
# Responsável por:
# - versão do DSM
# - sistema operacional
# - kernel
# - uptime
# - dependências externas
#
# =============================================================

LOG_MODULE="core"

readonly DSM_VERSION_FILE="${DSM_ROOT}/version"

# =============================================================
# Versão do DSM
# =============================================================
runtime_version()
{
    if [ -r "$DSM_VERSION_FILE" ]
    then
        cat "$DSM_VERSION_FILE"
    else
        echo "desconhecida"
    fi
}

# =============================================================
# Sistema Operacional
# =============================================================
runtime_os()
{
    if [ -r /etc/os-release ]
    then
        awk -F= '
        /^PRETTY_NAME=/{
            gsub(/"/,"",$2)
            print $2
        }' /etc/os-release
    else
        uname -s
    fi
}

# =============================================================
# Kernel
# =============================================================
runtime_kernel()
{
    uname -r
}

# =============================================================
# Hostname
# =============================================================
runtime_hostname()
{
    hostname 2>/dev/null || uname -n
}

# =============================================================
# Uptime do Host
# =============================================================
runtime_uptime()
{
    uptime -p 2>/dev/null || echo "desconhecido"
}

# =============================================================
# Dependências externas
#
# Não depende de cron.
#
# Scheduler usa daemon próprio.
# =============================================================
readonly RUNTIME_DEPENDENCIES=(
    curl
    jq
    tar
    rsync
    sha256sum
    python3
    systemctl
)

# =============================================================
# Dependências ausentes
# =============================================================
runtime_missing_deps()
{
    local cmd

    for cmd in "${RUNTIME_DEPENDENCIES[@]}"
    do
        command -v "$cmd" >/dev/null 2>&1 || echo "$cmd"
    done
}

# =============================================================
# Verificação completa
# =============================================================
runtime_check_deps()
{
    local missing

    mapfile -t missing < <(runtime_missing_deps)

    if [ "${#missing[@]}" -gt 0 ]
    then
        log_warn \
        "Dependências ausentes: ${missing[*]}"
        return 1
    fi

    log_ok \
    "Todas as dependências externas estão presentes"

    return 0
}

# =============================================================
# Informações consolidadas
#
# Utilizado por:
# - Doctor
# - Dashboard
# - API
#
# =============================================================
runtime_info()
{
cat <<EOF
{
  "dsm_version":"$(runtime_version)",
  "os":"$(runtime_os)",
  "kernel":"$(runtime_kernel)",
  "hostname":"$(runtime_hostname)",
  "instance":"${INSTANCE_NAME:-desconhecida}",
  "uptime":"$(runtime_uptime)"
}
EOF
}

# =============================================================
# Teste direto
# =============================================================
if [ "${BASH_SOURCE[0]}" = "$0" ]
then
    runtime_check_deps
    runtime_info
fi
