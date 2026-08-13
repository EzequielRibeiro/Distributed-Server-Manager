#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
#
# Minecraft Game Launcher
#
# Responsável por:
#
# - iniciar servidor Minecraft
# - utilizar contexto da instância
# - não possuir configurações fixas
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# =============================================================
# Carrega contexto DSM
# =============================================================

source "${DSM_ROOT}/core/process/context.sh"


# =============================================================
# Carrega configuração da instância
# =============================================================

if [[ -z "${DSM_INSTANCE_PATH:-}" ]]
then
    echo "Instância não definida."
    exit 1
fi


if [[ -f "${DSM_INSTANCE_PATH}/instance.conf" ]]
then
    source "${DSM_INSTANCE_PATH}/instance.conf"
else
    echo "Configuração da instância não encontrada:"
    echo "${DSM_INSTANCE_PATH}/instance.conf"
    exit 1
fi



# =============================================================
# Minecraft Start
# =============================================================

minecraft_start()
{

echo
echo "======================================"
echo " Minecraft Launcher"
echo "======================================"

echo "Node:      ${DSM_NODE}"
echo "Instance:  ${DSM_INSTANCE}"
echo "Port:      ${SERVER_PORT}"
echo "Memory:    ${JAVA_MIN_RAM} - ${JAVA_MAX_RAM}"
echo


cd "${SERVERFILES_PATH}" || return 1



# Aceita diferentes jars:
#
# server.jar
# paper.jar
# fabric-server-launch.jar
#

JAVA_FILE="${SERVER_JAR:-server.jar}"


if [[ ! -f "${JAVA_FILE}" ]]
then
    echo "Arquivo Java não encontrado:"
    echo "${JAVA_FILE}"
    return 1
fi



java \
-Xms"${JAVA_MIN_RAM:-2G}" \
-Xmx"${JAVA_MAX_RAM:-8G}" \
-Dserver.port="${SERVER_PORT}" \
-jar "${JAVA_FILE}" \
nogui


}



# =============================================================
# Minecraft Stop
# =============================================================

minecraft_stop()
{

echo "Solicitando parada Minecraft"


if [[ -f "${DSM_INSTANCE_PATH}/console.stdin" ]]
then

    echo "stop" > "${DSM_INSTANCE_PATH}/console.stdin"

else

    echo "Console Minecraft não encontrado."

fi

}



# =============================================================
# Minecraft Restart
# =============================================================

minecraft_restart()
{

minecraft_stop


sleep "${RESTART_DELAY:-10}"


minecraft_start

}



# =============================================================
# Status
# =============================================================

minecraft_status()
{

if declare -F process_status >/dev/null
then
    process_status
else
    echo "Process Manager indisponível."
fi

}



# =============================================================
# PID
# =============================================================

minecraft_pid()
{

if declare -F process_pid >/dev/null
then
    process_pid
fi

}



# =============================================================
# Dispatcher
# =============================================================

case "${1:-}" in

start)

    minecraft_start
;;

stop)

    minecraft_stop
;;

restart)

    minecraft_restart
;;

status)

    minecraft_status
;;

pid)

    minecraft_pid
;;

*)

echo
echo "Uso:"
echo
echo " launcher.sh start"
echo " launcher.sh stop"
echo " launcher.sh restart"
echo " launcher.sh status"
echo " launcher.sh pid"

;;

esac