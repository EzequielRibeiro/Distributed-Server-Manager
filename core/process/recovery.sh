#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
#
# Process Recovery Engine
#
# Responsável:
#
# - recuperar instâncias falhadas
# - remover processos antigos
# - executar launcher da instância
# - validar novo processo
#
# =============================================================


set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# =============================================================
# Carrega contexto do Agent
# =============================================================

source "${DSM_ROOT}/config/runtime.sh"


# =============================================================
# Carrega módulos de processo
# =============================================================

source "${DSM_ROOT}/core/process/process.sh"
source "${DSM_ROOT}/core/process/pid.sh"
source "${DSM_ROOT}/core/process/tree.sh"



# =============================================================
# Parâmetros
# =============================================================

RECOVERY_REASON="${1:-unknown}"


INSTANCE_ID="${DSM_INSTANCE_ID:-${2:-}}"


if [[ -z "${INSTANCE_ID}" ]]
then
    echo "Instância não informada."
    exit 1
fi



# =============================================================
# Contexto da instância
# =============================================================


INSTANCE_PATH="${INSTANCE_ROOT}/${INSTANCE_ID}"


INSTANCE_RUNTIME="${INSTANCE_PATH}/runtime"


INSTANCE_LAUNCHER="${INSTANCE_PATH}/launcher.sh"


PROCESS_PID_FILE="${INSTANCE_RUNTIME}/process.pid"


RECOVERY_LOG="${INSTANCE_RUNTIME}/recovery.log"


RECOVERY_STATE="${INSTANCE_RUNTIME}/recovery.json"



mkdir -p "${INSTANCE_RUNTIME}"



# =============================================================
# Log
# =============================================================

recovery_log()
{

echo "$(date '+%Y-%m-%d %H:%M:%S') $*" \
>> "${RECOVERY_LOG}"

}



# =============================================================
# Estado
# =============================================================

recovery_state()
{

local STATUS="$1"


cat > "${RECOVERY_STATE}" <<EOF
{
 "node":"${DSM_NODE_ID}",
 "instance":"${INSTANCE_ID}",
 "status":"${STATUS}",
 "reason":"${RECOVERY_REASON}",
 "timestamp":"$(date -Iseconds)"
}
EOF

}



# =============================================================
# Evento
# =============================================================

recovery_event()
{


if command -v dsm >/dev/null 2>&1
then

dsm events add \
"process_recovery" \
"${INSTANCE_ID}" \
"${RECOVERY_REASON}" \
|| true

fi


}



# =============================================================
# Finalizar processo antigo
# =============================================================

cleanup_process()
{

PID="$(process_pid "${INSTANCE_ID}" || true)"


if [[ -z "${PID}" ]]
then
    return 0
fi



if kill -0 "${PID}" 2>/dev/null
then

recovery_log \
"Encerrando árvore PID=${PID}"


process_kill_tree "${PID}"

fi



rm -f "${PROCESS_PID_FILE}"

}



# =============================================================
# Limpa runtime antigo
# =============================================================

cleanup_runtime()
{


rm -f \
"${PROCESS_PID_FILE}"


rm -f \
"${INSTANCE_RUNTIME}/watchdog.json"


}



# =============================================================
# Inicia instância
# =============================================================

start_instance()
{


if [[ ! -x "${INSTANCE_LAUNCHER}" ]]
then

recovery_log \
"Launcher não encontrado: ${INSTANCE_LAUNCHER}"

return 1

fi



recovery_log \
"Executando launcher"



"${INSTANCE_LAUNCHER}" start



}



# =============================================================
# Valida novo processo
# =============================================================

validate_instance()
{


local TIMEOUT=60

local COUNT=0



while [[ ${COUNT} -lt ${TIMEOUT} ]]
do


PID="$(process_pid "${INSTANCE_ID}" || true)"



if [[ -n "${PID}" ]]
then


if process_pid_validate "${PID}"
then


recovery_log \
"Novo processo válido PID=${PID}"


return 0


fi


fi



sleep 5


COUNT=$((COUNT+5))


done



return 1

}



# =============================================================
# Recovery principal
# =============================================================

recovery_run()
{


recovery_log \
"Recovery iniciado: ${RECOVERY_REASON}"



recovery_state \
"recovering"



recovery_event



cleanup_process


cleanup_runtime



if ! start_instance
then

recovery_state \
"failed"


exit 1

fi



if validate_instance
then


recovery_state \
"recovered"


recovery_log \
"Recovery concluído"



else


recovery_state \
"failed"


recovery_log \
"Falha ao validar processo"



exit 1


fi


}



recovery_run