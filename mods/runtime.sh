#!/bin/bash
# =============================================================
# DSM Mods Runtime
#
# Commit 15
#
# Integra Mods com DSM Runtime
#
# =============================================================


set -euo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


RUNTIME="$DSM_ROOT/runtime"

MOD_RUNTIME="$RUNTIME/mods/state.json"

MOD_RUNTIME=$(runtime_resource_path)/mods.json

mkdir -p "$(dirname "$MOD_RUNTIME")"



# =============================================================
# Dependências
# =============================================================


source "$DSM_ROOT/core/events.sh"



# =============================================================
# Identidade
# =============================================================


SERVER="${DSM_SERVER:-server01}"
GAME="${DSM_GAME:-dayz}"
INSTANCE="${DSM_INSTANCE:-survival01}"



# =============================================================
# Estado inicial
# =============================================================


init_state()
{

if [ ! -f "$MOD_RUNTIME" ]
then

cat > "$MOD_RUNTIME" <<JSON
{
  "module":"mods",
  "status":"unknown",
  "mods":0,
  "keys":0,
  "last_update":0
}
JSON

fi


if ! jq -e 'type=="object"' "$MOD_RUNTIME" >/dev/null 2>&1
then

cat > "$MOD_RUNTIME" <<JSON
{
  "module":"mods",
  "status":"unknown",
  "mods":0,
  "keys":0,
  "last_update":0
}
JSON

fi

}



# =============================================================
# Atualizar estado
# =============================================================
# =============================================================
# Atualizar Runtime
# =============================================================

mods_runtime_update()
{
    local STATUS="${1:-unknown}"
    local MODS="${2:-0}"
    local KEYS="${3:-0}"
    local BROKEN_FOLDER_LINKS="${4:-0}"
    local MISSING_META="${5:-0}"
    local INVALID_MODS="${6:-0}"

    init_state

    jq \
        --arg status "$STATUS" \
        --argjson mods "$MODS" \
        --argjson keys "$KEYS" \
        --argjson broken "$BROKEN_FOLDER_LINKS" \
        --argjson meta "$MISSING_META" \
        --argjson invalid "$INVALID_MODS" \
        --argjson timestamp "$(date +%s)" \
        '
        .module = "mods" |
        .status = $status |
        .mods = $mods |
        .keys = $keys |
        .broken_folder_links = $broken |
        .missing_meta = $meta |
        .invalid_mods = $invalid |
        .last_update = $timestamp
        ' \
        "$MOD_RUNTIME" \
        > "${MOD_RUNTIME}.tmp"

    mv "${MOD_RUNTIME}.tmp" "$MOD_RUNTIME"
}



# =============================================================
# Evento
# =============================================================


mods_runtime_event()
{

local TYPE="$1"
local MESSAGE="$2"


event_info \
"$TYPE" \
mod \
"$MESSAGE" \
DSM \
"$SERVER" \
"$GAME" \
"$INSTANCE"

}



# =============================================================
# Atualização Runtime
# =============================================================


runtime_update()
{



KEY_DIR="${SERVERFILES_PATH:-/home/mine/steamcmd/serverfiles}/keys"
MODS_PATH="${SERVERFILES_PATH:-/home/mine/steamcmd/serverfiles}/mods"


MOD_COUNT=$(find "$MODS_PATH" \
-maxdepth 1 \
-name "@*" \
\( -type d -o -type l \) \
| while read mod
do

    if [ -d "$mod" ]
    then
        echo "$mod"
    fi

done \
| wc -l)



KEY_COUNT=$(find "$KEY_DIR" \
-type f \
-name "*.bikey" \
2>/dev/null \
| wc -l)



mods_runtime_update \
"healthy" \
"$MOD_COUNT" \
"$KEY_COUNT"



event_success \
MOD_RUNTIME_UPDATED \
mod \
"Mods runtime updated (${MOD_COUNT} mods, ${KEY_COUNT} keys)" \
DSM \
"$SERVER" \
"$GAME" \
"$INSTANCE"



echo "[OK] Runtime Mods atualizado"

}



# =============================================================
# Status
# =============================================================


runtime_status()
{

init_state

jq . "$MOD_RUNTIME"

}

# =============================================================
# Execução direta
# =============================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then

    case "${1:-}" in

        update)
            runtime_update
        ;;

        status)
            runtime_status
        ;;

        *)
            echo
            echo "DSM Mods Runtime"
            echo
            echo "Uso:"
            echo
            echo " runtime.sh update"
            echo " runtime.sh status"
            echo
            exit 1
        ;;

    esac

fi



