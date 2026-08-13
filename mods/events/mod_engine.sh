#!/bin/bash

# =============================================================
# DSM Mod Event Engine
#
# Commit 15
#
# Integração:
#
# mod_engine.sh
#       |
#       +--> mod_state.sh update
#       |
#       +--> event_manager.sh
#
# =============================================================


set -e



DSM_ROOT="${DSM_ROOT:-/opt/dsm}"



# =============================================================
# Configuração
# =============================================================

[ -f "$DSM_ROOT/config/dsm.conf" ] &&
source "$DSM_ROOT/config/dsm.conf"



PARSER="$DSM_ROOT/mods/events/mod_parser.py"

MOD_STATE="$DSM_ROOT/mods/events/mod_state.sh"

EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"



SERVER="${DSM_SERVER_ID:-unknown}"

GAME="${DSM_GAME:-unknown}"

INSTANCE="${DSM_INSTANCE:-unknown}"



# =============================================================
# Processa evento de Mod
# =============================================================

process()
{

LINE="$1"



EVENT=$(echo "$LINE" | \
python3 "$PARSER")



TYPE=$(echo "$EVENT" | jq -r '.type')



MESSAGE=$(echo "$EVENT" | \
jq -r '.data.raw')



#
# Nome do mod
#
# Futuro parser poderá enviar:
#
# .resource.mod
#
# fallback atual:
#
MOD_NAME=$(echo "$EVENT" | \
jq -r '.resource.mod // .data.mod // "unknown"')



# =============================================================
# Atualiza estado local do Mod
# =============================================================

"$MOD_STATE" \
update \
"$MOD_NAME" \
"$TYPE"



# =============================================================
# Publica evento universal
# =============================================================

case "$TYPE" in


MOD_UPDATED)


"$EVENT_MANAGER" \
mod \
MOD_UPDATED \
"$MESSAGE" \
"$SERVER" \
"$GAME" \
"$INSTANCE"

;;



MOD_MISSING)


"$EVENT_MANAGER" \
mod \
MOD_MISSING \
"$MESSAGE" \
"$SERVER" \
"$GAME" \
"$INSTANCE"

;;



KEY_MISSING)


"$EVENT_MANAGER" \
mod \
KEY_MISSING \
"$MESSAGE" \
"$SERVER" \
"$GAME" \
"$INSTANCE"

;;



MOD_UPDATE_FAILED)


"$EVENT_MANAGER" \
mod \
MOD_UPDATE_FAILED \
"$MESSAGE" \
"$SERVER" \
"$GAME" \
"$INSTANCE"

;;



*)


"$EVENT_MANAGER" \
mod \
MOD_EVENT \
"$MESSAGE" \
"$SERVER" \
"$GAME" \
"$INSTANCE"

;;


esac


}



# =============================================================
# CLI
# =============================================================

case "$1" in


test)

process "$2"

;;



*)

echo "
DSM Mod Engine

Uso:

mod_engine.sh test \"mensagem\"

"

;;


esac