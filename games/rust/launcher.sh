#!/usr/bin/env bash
# =============================================================
# Capivara DSM
#
# Rust Launcher
#
# =============================================================

set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


source "${DSM_ROOT}/core/process/context.sh"



source "${DSM_INSTANCE_PATH}/instance.conf"



rust_start()
{

echo
echo "================================"
echo " Rust Launcher"
echo "================================"

echo "Instância: ${DSM_INSTANCE}"
echo "Porta: ${SERVER_PORT}"
echo



cd "${SERVERFILES_PATH}" || return 1



./RustDedicated \
-batchmode \
-nographics \
+server.hostname "${SERVER_NAME}" \
+server.port "${SERVER_PORT}" \
+server.queryport "${QUERY_PORT}" \
+server.identity "${DSM_INSTANCE}" \
+server.level "${SERVER_LEVEL:-Procedural Map}" \
+server.worldsize "${WORLD_SIZE:-4000}" \
+server.seed "${SERVER_SEED:-12345}" \
+server.maxplayers "${MAX_PLAYERS:-50}"

}



rust_stop()
{

echo "Parando Rust"


process_signal TERM

}



rust_restart()
{

rust_stop

sleep "${RESTART_DELAY:-10}"

rust_start

}



case "${1:-}" in

start)
rust_start
;;

stop)
rust_stop
;;

restart)
rust_restart
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