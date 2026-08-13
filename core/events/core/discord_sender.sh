#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
#
# Arquivo:
#   core/discord_sender.sh
#
# Função:
#   Envio automático da fila Discord
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

QUEUE="$DSM_ROOT/core/discord_queue.sh"
WEBHOOK="$DSM_ROOT/core/discord_webhook.sh"

LOG_FILE="$DSM_ROOT/logs/discord_sender.log"

# -------------------------------------------------------------
# Preparar ambiente
# -------------------------------------------------------------
init()
{
    mkdir -p "$(dirname "$LOG_FILE")"
}

# -------------------------------------------------------------
# Log
# -------------------------------------------------------------
log()
{
echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
>> "$LOG_FILE"
}

# -------------------------------------------------------------
# Enviar item
# -------------------------------------------------------------
send_item()
{
local item="$1"

local id
id=$(echo "$item" | jq -r '.id')

local type
type=$(echo "$item" | jq -r '.type')

local payload
payload=$(echo "$item" | jq -r '.payload')

log "Enviando mensagem $id"

if "$WEBHOOK" message "$payload"
then
    "$QUEUE" sent "$id"

    log "Mensagem enviada $id"

    return 0
else
    log "Falha envio $id"

    return 1
fi
}

# -------------------------------------------------------------
# Processar fila
# -------------------------------------------------------------
process_queue()
{
local pending
pending=$(
    "$QUEUE" pending
)

local total
total=$(echo "$pending" | jq length)

if [ "$total" -eq 0 ]; then
    log "Fila vazia"
    return 0
fi

for ((i=0;i<total;i++))
do
    item=$(
        echo "$pending" |
        jq ".[$i]"
    )

    send_item "$item"
done
}

# -------------------------------------------------------------
# Loop contínuo
# -------------------------------------------------------------
daemon()
{
while true
do
    process_queue
    sleep 5
done
}

# -------------------------------------------------------------
# Teste
# -------------------------------------------------------------
test()
{
"$QUEUE" add \
INFO \
"🟢 DSM Sender Teste OK"

process_queue
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
init

case "$1" in

once)
    process_queue
;;

daemon)
    daemon
;;

test)
    test
;;

*)
cat <<EOF


DSM Discord Sender v1.2.0


Uso:


Enviar fila:

 discord_sender.sh once



Modo serviço:

 discord_sender.sh daemon



Teste:

 discord_sender.sh test



EOF
;;
esac
