#!/bin/bash

# =============================================================
# DSM Discord Alert Sender
#
# Módulo:
#   11.3
#
# Uso:
#
# send_alert.sh LEVEL TITLE MESSAGE
#
# Exemplo:
#
# send_alert.sh CRITICAL "Servidor Offline" "DayZ caiu"
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

CONFIG="$DSM_ROOT/discord/discord.conf"

if [ ! -f "$CONFIG" ]
then
    echo "discord.conf não encontrado"
    exit 1
fi

source "$CONFIG"

if [ "$DISCORD_ENABLED" != "true" ]
then
    exit 0
fi

if [ -z "$DISCORD_WEBHOOK" ]
then
    echo "Webhook Discord não configurado"
    exit 1
fi

LEVEL="$1"
TITLE="$2"
MESSAGE="$3"

# -------------------------------------------------------------
# Cores Discord Embed
# -------------------------------------------------------------

case "$LEVEL" in
CRITICAL|ERROR)
COLOR=16711680
;;
WARNING|WARN)
COLOR=16753920
;;
INFO)
COLOR=3447003
;;
*)
COLOR=9807270
;;
esac

# -------------------------------------------------------------
# JSON Payload
# -------------------------------------------------------------

PAYLOAD=$(jq -n \
    --arg username "$DISCORD_USERNAME" \
    --arg title "$TITLE" \
    --arg message "$MESSAGE" \
    --arg level "$LEVEL" \
    --argjson color "$COLOR" \
'
{
 username:$username,
 embeds:[
  {
   title:$title,
   description:$message,
   color:$color,
   fields:[
    {
      name:"Nível",
      value:$level,
      inline:true
    },
    {
      name:"Servidor",
      value:"DSM Dashboard",
      inline:true
    }
   ]
  }
 ]
}
')

# -------------------------------------------------------------
# Envio
# -------------------------------------------------------------

curl \
 --silent \
 --show-error \
 --fail \
 --max-time "$DISCORD_TIMEOUT" \
 -H "Content-Type: application/json" \
 -X POST \
 -d "$PAYLOAD" \
 "$DISCORD_WEBHOOK"

RC=$?

if [ "$RC" -ne 0 ]
then
    echo "Falha ao enviar Discord"
    exit 1
fi

exit 0
