#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
#
# Arquivo:
#   core/discord_formatter.sh
#
# Função:
#   Gerar mensagens Discord Embed
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

HOSTNAME=$(hostname)
DSM_VERSION="v1.2.0"

# -------------------------------------------------------------
# Cores Discord Embed
# -------------------------------------------------------------
COLOR_CRITICAL=16711680
COLOR_WARNING=16753920
COLOR_OK=5763719
COLOR_INFO=3447003

# -------------------------------------------------------------
# Escape JSON
# -------------------------------------------------------------
json_escape()
{
    echo "$1" \
    | sed \
    's/\\/\\\\/g;
     s/"/\\"/g;
     s/$/ /'
}

# -------------------------------------------------------------
# Gerar Embed genérico
# -------------------------------------------------------------
create_embed()
{
    local color="$1"
    local title="$2"
    local description="$3"

jq -n \
--arg title "$title" \
--arg description "$description" \
--arg hostname "$HOSTNAME" \
--arg version "$DSM_VERSION" \
--arg time "$(date -Iseconds)" \
--argjson color "$color" \
'
{
 "embeds":[
   {
    "title":$title,
    "description":$description,
    "color":$color,

    "fields":[

      {
       "name":"Servidor",
       "value":$hostname,
       "inline":true
      },

      {
       "name":"DSM",
       "value":$version,
       "inline":true
      }

    ],

    "footer":{
       "text":"DSM Alert Manager"
    },

    "timestamp":$time

   }
 ]
}
'
}

# -------------------------------------------------------------
# Alerta crítico
# -------------------------------------------------------------
format_critical()
{
local title="$1"
local message="$2"

create_embed \
"$COLOR_CRITICAL" \
"🔴 DSM CRITICAL ALERT - $title" \
"$message"
}

# -------------------------------------------------------------
# Alerta warning
# -------------------------------------------------------------
format_warning()
{
local title="$1"
local message="$2"

create_embed \
"$COLOR_WARNING" \
"🟡 DSM WARNING - $title" \
"$message"
}

# -------------------------------------------------------------
# Recuperação
# -------------------------------------------------------------
format_recovery()
{
local title="$1"
local message="$2"

create_embed \
"$COLOR_OK" \
"🟢 DSM RECOVERY - $title" \
"$message"
}

# -------------------------------------------------------------
# Informação
# -------------------------------------------------------------
format_info()
{
local title="$1"
local message="$2"

create_embed \
"$COLOR_INFO" \
"🔵 DSM INFO - $title" \
"$message"
}

# -------------------------------------------------------------
# Relatório de status
# -------------------------------------------------------------
format_status()
{
local cpu="$1"
local memory="$2"
local disk="$3"
local uptime="$4"

jq -n \
--arg hostname "$HOSTNAME" \
--arg cpu "$cpu" \
--arg memory "$memory" \
--arg disk "$disk" \
--arg uptime "$uptime" \
--arg version "$DSM_VERSION" \
--arg time "$(date -Iseconds)" \
'
{
 "embeds":[
  {

   "title":"📊 DSM STATUS REPORT",

   "color":3447003,


   "fields":[


    {
     "name":"CPU Host",
     "value":$cpu,
     "inline":true
    },


    {
     "name":"Memória",
     "value":$memory,
     "inline":true
    },


    {
     "name":"Disco",
     "value":$disk,
     "inline":true
    },


    {
     "name":"Uptime",
     "value":$uptime,
     "inline":false
    },


    {
     "name":"Servidor",
     "value":$hostname,
     "inline":false
    },


    {
     "name":"DSM",
     "value":$version,
     "inline":false
    }


   ],


   "timestamp":$time

  }
 ]
}
'
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
case "$1" in

critical)
format_critical \
"$2" \
"$3"
;;

warning)
format_warning \
"$2" \
"$3"
;;

recovery)
format_recovery \
"$2" \
"$3"
;;

info)
format_info \
"$2" \
"$3"
;;

status)
format_status \
"$2" \
"$3" \
"$4" \
"$5"
;;

*)
cat <<EOF


DSM Discord Formatter v1.2.0


Uso:


Alerta crítico:

discord_formatter.sh critical \
"Título" \
"Mensagem"



Warning:

discord_formatter.sh warning \
"Título" \
"Mensagem"



Recuperação:

discord_formatter.sh recovery \
"Título" \
"Mensagem"



Status:

discord_formatter.sh status \
"CPU" \
"RAM" \
"DISCO" \
"UPTIME"



EOF
;;
esac
