#!/usr/bin/env bash
# =============================================================
# Capivara DSM
#
# Arma 3 Launcher
#
# =============================================================


set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


source "${DSM_ROOT}/core/process/context.sh"


source "${DSM_INSTANCE_PATH}/instance.conf"



arma3_start()
{

echo
echo "================================"
echo " Arma 3 Launcher"
echo "================================"


echo "Instância: ${DSM_INSTANCE}"
echo "Porta: ${SERVER_PORT}"


cd "${SERVERFILES_PATH}" || return 1



./arma3server_x64 \
-port="${SERVER_PORT}" \
-config="${SERVER_CONFIG}" \
-cfg="${SERVER_CFG}" \
-profiles="${PROFILES_PATH}" \
-name="${DSM_INSTANCE}" \
-mod="${SERVER_MODS}" \
-serverMod="${SERVER_SERVERMODS:-}"

}



arma3_stop()
{

echo "Parando Arma 3"


process_signal TERM

}



arma3_restart()
{

arma3_stop

sleep "${RESTART_DELAY:-10}"

arma3_start

}



case "${1:-}" in


start)
arma3_start
;;


stop)
arma3_stop
;;


restart)
arma3_restart
;;


status)
process_status
;;


pid)
process_pid
;;


*)

echo "Uso:"
echo " launcher.sh start|stop|restart|status|pid"

;;


esac