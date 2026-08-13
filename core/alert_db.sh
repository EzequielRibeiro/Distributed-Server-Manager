#!/bin/bash
# =============================================================
# DSM Core v1.2.0
#
# Arquivo:
#   core/alert_db.sh
#
# Função:
#   Camada de persistência dos alertas DSM
#
# Banco atual:
#   Arquivo texto estruturado
#
# Formato:
#
# id|state|level|created|updated|message
#
# Exemplo:
#
# cpu-host|OPEN|CRITICAL|2026-07-27T20:00:00|2026-07-27T20:00:00|CPU alta
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

ALERT_DB_DIR="$DSM_ROOT/runtime/alerts"
ALERT_DB_FILE="$ALERT_DB_DIR/alerts.db"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
alert_db_init()
{
    mkdir -p "$ALERT_DB_DIR"

    if [ ! -f "$ALERT_DB_FILE" ]; then
        touch "$ALERT_DB_FILE"
    fi
}

# -------------------------------------------------------------
# Inserir alerta
#
# Parâmetros:
#
# $1 id
# $2 estado
# $3 nível
# $4 mensagem
#
# -------------------------------------------------------------
alert_db_insert()
{
    local id="$1"
    local state="$2"
    local level="$3"
    local message="$4"

    alert_db_init

    local now
    now="$(date -Iseconds)"

    echo "$id|$state|$level|$now|$now|$message" \
    >> "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Buscar alerta pelo ID
# -------------------------------------------------------------
alert_db_get()
{
    local id="$1"

    alert_db_init

    grep "^${id}|" "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Verifica existência
# -------------------------------------------------------------
alert_db_exists()
{
    local id="$1"

    alert_db_get "$id" >/dev/null 2>&1
}

# -------------------------------------------------------------
# Atualizar estado
#
# $1 id
# $2 novo estado
#
# -------------------------------------------------------------
alert_db_update_state()
{
    local id="$1"
    local state="$2"

    alert_db_init

    local line
    line="$(alert_db_get "$id")"

    [ -z "$line" ] && return 1

    local level
    local created
    local message

    level="$(echo "$line" | cut -d'|' -f3)"
    created="$(echo "$line" | cut -d'|' -f4)"
    message="$(echo "$line" | cut -d'|' -f6)"

    local tmp
    tmp="${ALERT_DB_FILE}.tmp"

    grep -v "^${id}|" "$ALERT_DB_FILE" > "$tmp"

    echo "$id|$state|$level|$created|$(date -Iseconds)|$message" \
    >> "$tmp"

    mv "$tmp" "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Remover alerta
# -------------------------------------------------------------
alert_db_delete()
{
    local id="$1"

    alert_db_init

    local tmp
    tmp="${ALERT_DB_FILE}.tmp"

    grep -v "^${id}|" "$ALERT_DB_FILE" \
    > "$tmp"

    mv "$tmp" "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Listar todos
# -------------------------------------------------------------
alert_db_list()
{
    alert_db_init
    cat "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Listar por estado
#
# OPEN
# ACKNOWLEDGED
# RESOLVED
# SUPPRESSED
#
# -------------------------------------------------------------
alert_db_list_state()
{
    local state="$1"

    alert_db_init

    awk -F"|" -v s="$state" '$2==s' \
    "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Listar por nível
#
# CRITICAL
# WARNING
# INFO
#
# -------------------------------------------------------------
alert_db_list_level()
{
    local level="$1"

    alert_db_init

    awk -F"|" -v l="$level" '$3==l' \
    "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Contagem
# -------------------------------------------------------------
alert_db_count()
{
    local filter="$1"

    alert_db_init

    case "$filter" in

        ALL)
            wc -l < "$ALERT_DB_FILE"
        ;;

        OPEN|ACKNOWLEDGED|RESOLVED|SUPPRESSED)
            alert_db_list_state "$filter" |
            wc -l
        ;;

        CRITICAL|WARNING|INFO)
            alert_db_list_level "$filter" |
            wc -l
        ;;

        *)
            echo 0
        ;;
esac
}

# -------------------------------------------------------------
# Limpeza de histórico antigo
#
# Remove alertas resolvidos antigos
#
# -------------------------------------------------------------
alert_db_cleanup()
{
    local days="${1:-30}"

    alert_db_init

    local tmp
    tmp="${ALERT_DB_FILE}.tmp"

    while IFS="|" read -r id state level created updated msg
    do
        if [ "$state" != "RESOLVED" ]; then
            echo "$id|$state|$level|$created|$updated|$msg" \
            >> "$tmp"
        fi
    done < "$ALERT_DB_FILE"

    mv "$tmp" "$ALERT_DB_FILE"
}

# -------------------------------------------------------------
# Export JSON
# -------------------------------------------------------------
alert_db_json()
{
    alert_db_init

    echo "["
    local first=1

    while IFS="|" read -r id state level created updated msg
    do
        [ -z "$id" ] && continue

        [ "$first" -eq 0 ] && echo ","

        first=0

cat <<EOF
{
 "id":"$id",
 "state":"$state",
 "level":"$level",
 "created":"$created",
 "updated":"$updated",
 "message":"$msg"
}
EOF
    done < "$ALERT_DB_FILE"

    echo "]"
}

# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
case "$1" in

init)
    alert_db_init
;;

insert)
    alert_db_insert "$2" "$3" "$4" "$5"
;;

get)
    alert_db_get "$2"
;;

list)
    alert_db_list
;;

json)
    alert_db_json
;;

count)
    alert_db_count "$2"
;;

update)
    alert_db_update_state "$2" "$3"
;;

delete)
    alert_db_delete "$2"
;;

cleanup)
    alert_db_cleanup "$2"
;;

*)

cat <<EOF

DSM Alert Database

Uso:

 alert_db.sh init

 alert_db.sh insert <id> <state> <level> <message>

 alert_db.sh get <id>

 alert_db.sh list

 alert_db.sh json

 alert_db.sh count <tipo>

 alert_db.sh update <id> <state>

 alert_db.sh delete <id>

 alert_db.sh cleanup <dias>

EOF
;;
esac
fi
