#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
#
# Process Watchdog
#
# Responsável por:
#
# - monitorar processos
# - detectar falhas
# - acionar recovery
#
# =============================================================


set -Eeuo pipefail



DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


source "${DSM_ROOT}/config/runtime.sh"
source "${DSM_ROOT}/core/process/process.sh"
source "${DSM_ROOT}/core/process/pid.sh"
source "${DSM_ROOT}/core/process/status.sh"
source "${DSM_ROOT}/core/process/tree.sh"



# =============================================================
# Runtime
# =============================================================


WATCHDOG_INTERVAL="${WATCHDOG_INTERVAL:-30}"


WATCHDOG_STATE="${DSM_INSTANCE_PATH}/runtime/watchdog.json"


WATCHDOG_LOG="${DSM_LOG_DIR}/watchdog.log"



mkdir -p "$(dirname "${WATCHDOG_STATE}")"



# =============================================================
# Log
# =============================================================


watchdog_log()
{

echo "$(date '+%Y-%m-%d %H:%M:%S') $*" \
>> "${WATCHDOG_LOG}"

}



# =============================================================
# Atualiza estado
# =============================================================


watchdog_state()
{

cat > "${WATCHDOG_STATE}" <<EOF
{
 "instance":"${DSM_INSTANCE}",
 "pid":"${1}",
 "status":"${2}",
 "time":"$(date -Iseconds)"
}
EOF

}



# =============================================================
# PID desapareceu
# =============================================================


watchdog_pid_check()
{

local PID="$1"



if [[ -z "${PID}" ]]
then

return 1

fi



if ! kill -0 "${PID}" 2>/dev/null
then

watchdog_log \
"PID desapareceu: ${PID}"

return 1

fi



return 0

}



# =============================================================
# Processo travado
# =============================================================

watchdog_process_check()
{

local PID="$1"



#
# Verifica estado Linux
#

STATE=$(ps -o stat= -p "${PID}" | tr -d ' ')



case "${STATE}" in


D*)

watchdog_log \
"Processo bloqueado estado D PID=${PID}"

return 1

;;


Z*)

watchdog_log \
"Processo zombie PID=${PID}"

return 1

;;


*)

return 0

;;

esac

}



# =============================================================
# Processo filho órfão
# =============================================================


watchdog_children_check()
{


local PID="$1"



CHILDREN=$(process_children "${PID}")


if [[ -z "${CHILDREN}" ]]
then

return 0

fi



for CHILD in ${CHILDREN}
do


PPID=$(ps -o ppid= -p "${CHILD}" | tr -d ' ')



if [[ "${PPID}" != "${PID}" ]]
then

watchdog_log \
"Filho órfão encontrado ${CHILD}"


return 1

fi


done



return 0

}



# =============================================================
# Falha detectada
# =============================================================


watchdog_failure()
{

local REASON="$1"



watchdog_log \
"Falha detectada: ${REASON}"



watchdog_state \
"${PROCESS_PID:-0}" \
"failed"



if [[ -x "${DSM_ROOT}/core/process/recovery.sh" ]]
then


"${DSM_ROOT}/core/process/recovery.sh" \
"${REASON}"


fi


}



# =============================================================
# Ciclo único
# =============================================================


watchdog_check()
{


PID="$(process_pid || true)"



if [[ -z "${PID}" ]]
then

watchdog_failure \
"PID ausente"

return

fi



if ! process_pid_validate "${PID}"
then

watchdog_failure \
"PID inválido"

return

fi



if ! watchdog_pid_check "${PID}"
then

watchdog_failure \
"PID desapareceu"

return

fi



if ! watchdog_process_check "${PID}"
then

watchdog_failure \
"Processo travado"

return

fi



if ! watchdog_children_check "${PID}"
then

watchdog_failure \
"Filho órfão"

return

fi



watchdog_state \
"${PID}" \
"healthy"


}



# =============================================================
# LOOP
# =============================================================


watchdog_run()
{


watchdog_log \
"Watchdog iniciado"



while true
do


watchdog_check


sleep "${WATCHDOG_INTERVAL}"


done


}



case "${1:-}" in


once)

watchdog_check

;;


start)

watchdog_run

;;


*)

echo
echo "Uso:"
echo
echo "process_watchdog.sh once"
echo "process_watchdog.sh start"

;;

esac