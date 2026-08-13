#!/bin/bash

# =============================================================
# core/runtime.sh - MÓDULO 01 (CORE)
#
# Ambiente de execução DSM
#
# Responsável por:
#
# - versão DSM
# - sistema operacional
# - kernel
# - uptime
# - dependências
# - publicação Runtime
#
# =============================================================


LOG_MODULE="core"


readonly DSM_VERSION_FILE="${DSM_ROOT}/version"


# =============================================================
# Versão DSM
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

/^PRETTY_NAME=/
{
gsub(/"/,"",$2)
print $2
}

' /etc/os-release


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
# Uptime
# =============================================================

runtime_uptime()
{

uptime -p 2>/dev/null || echo "desconhecido"

}



# =============================================================
# Dependências externas
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



runtime_missing_deps()
{

local cmd


for cmd in "${RUNTIME_DEPENDENCIES[@]}"
do

command -v "$cmd" >/dev/null 2>&1 || echo "$cmd"

done

}



runtime_check_deps()
{

local missing


mapfile -t missing < <(
runtime_missing_deps
)



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
# Informações do ambiente
#
# Continua compatível com Doctor/API
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
# Publicação no Runtime Engine
#
# Sprint 2.2
#
# =============================================================


runtime_publish()
{

if [ -f "${DSM_ROOT}/core/runtime_engine.sh" ]
then


source "${DSM_ROOT}/core/runtime_engine.sh"



runtime_update \
"core" \
"$(runtime_info)"



fi

}



# =============================================================
# Inicialização Runtime
# =============================================================


runtime_init()
{

runtime_publish

}



runtime_pid()
{
    game_pid
}


runtime_start()
{
    game_start
}


runtime_stop()
{
    game_stop
}


runtime_restart()
{
    game_restart
}


runtime_status()
{
    game_status
}


# =============================================================
# Execução direta
# =============================================================


if [ "${BASH_SOURCE[0]}" = "$0" ]
then


runtime_check_deps

runtime_info


fi


export -f runtime_pid
export -f runtime_start
export -f runtime_stop
export -f runtime_restart
export -f runtime_status