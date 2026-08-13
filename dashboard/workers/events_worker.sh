#!/usr/bin/env bash

# =============================================================
# DSM Events Worker v2.1
#
# Commit 14A
#
# Integração automática Event Core
#
# Modelo:
#
# SERVER / GAME / INSTANCE
#
# =============================================================


set -Eeuo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

source "$DSM_ROOT/config/dsm.conf"

DSM_INTERVAL="${DSM_INTERVAL:-10}"


LOG_FILE="$DSM_ROOT/logs/dsm.log"


EVENT_MANAGER="$DSM_ROOT/events/event_manager.sh"

CURSOR_FILE="$DSM_ROOT/runtime/events/events_worker.cursor"

# =============================================================
# Identidade do recurso
# =============================================================

DSM_SERVER="${DSM_SERVER:-server01}"

DSM_GAME="${DSM_GAME:-dayz}"

DSM_INSTANCE="${DSM_INSTANCE:-survival01}"



# Carrega configuração DSM se existir

if [ -f "$DSM_ROOT/config/dsm.conf" ]
then

    source "$DSM_ROOT/config/dsm.conf"

fi



# =============================================================
# Gerador de evento
# =============================================================

process_event()
{

local MESSAGE="$1"

echo "$(date) EVENT: $MESSAGE" >> "$DSM_ROOT/logs/events_worker.log"

case "$MESSAGE" in

*SERVER_START*|*"started"*|*"START"*)

"$EVENT_MANAGER" \
server \
SERVER_START \
"$MESSAGE" \
"${DSM_SERVER_ID:-unknown}" \
"${DSM_GAME:-unknown}" \
"${DSM_INSTANCE:-unknown}"

;;

*SERVER_STOP*|*"stopped"*|*"STOP"*)

"$EVENT_MANAGER" \
server \
SERVER_STOP \
"$MESSAGE" \
"${DSM_SERVER_ID:-unknown}" \
"${DSM_GAME:-unknown}" \
"${DSM_INSTANCE:-unknown}"

;;

*"backup"*)

"$EVENT_MANAGER" \
backup \
BACKUP_CREATED \
"$MESSAGE" \
"${DSM_SERVER_ID}" \
"${DSM_GAME}" \
"${DSM_INSTANCE}"

;;

esac

}

# =============================================================
# Coleta incremental
# =============================================================

collect()
{
    [ -f "$LOG_FILE" ] || return

    mkdir -p "$(dirname "$CURSOR_FILE")"

    [ -f "$CURSOR_FILE" ] || echo 0 > "$CURSOR_FILE"

    local LAST_LINE CURRENT_LINE

    LAST_LINE=$(<"$CURSOR_FILE")
    CURRENT_LINE=$(wc -l < "$LOG_FILE")

    (( CURRENT_LINE > LAST_LINE )) || return

    while IFS= read -r line
    do
        process_event "$line"
    done < <(
        sed -n "$((LAST_LINE+1)),$CURRENT_LINE p" "$LOG_FILE"
    )

    echo "$CURRENT_LINE" > "$CURSOR_FILE"
}



# =============================================================
# Loop
# =============================================================

while true
do

    collect || true

    sleep "$DSM_INTERVAL"

done

