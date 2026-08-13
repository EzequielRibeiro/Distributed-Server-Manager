#!/bin/bash

# =============================================================
# DSM Discord Worker
#
# Módulo:
#   11.3
#
# Responsabilidade:
#
#   - Monitorar fila de notificações
#   - Executar Notification Engine
#   - Garantir envio Discord
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

INTERVAL=10

ENGINE="$DSM_ROOT/dashboard/notifications/notification_engine.sh"

if [ ! -x "$ENGINE" ]
then
    echo "Notification Engine não encontrado"
    exit 1
fi

echo "DSM Discord Worker iniciado."

while true
do
    "$ENGINE"
    sleep "$INTERVAL"
done
