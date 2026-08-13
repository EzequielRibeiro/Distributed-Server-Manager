#!/bin/bash
# =============================================================
# DSM Core v1.2.0
#
# Arquivo:
#   core/alert_history.sh
#
# Função:
#   Histórico e auditoria dos alertas DSM
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

HISTORY_DIR="$DSM_ROOT/runtime/alerts"
HISTORY_FILE="$HISTORY_DIR/history.log"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
alert_history_init()
{
    mkdir -p "$HISTORY_DIR"

    if [ ! -f "$HISTORY_FILE" ]; then
        touch "$HISTORY_FILE"
    fi
}

# -------------------------------------------------------------
# Registrar evento
#
# $1 ação
# $2 id
# $3 nível
# $4 estado anterior
# $5 estado novo
# $6 mensagem
#
# -------------------------------------------------------------
alert_history_write()
{
    local action="$1"
    local id="$2"
    local level="$3"
    local old_state="$4"
    local new_state="$5"
    local message="$6"

    alert_history_init

    echo "$(date -Iseconds)|$action|$id|$level|$old_state|$new_state|$message" \
    >> "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Eventos recentes
#
# padrão: últimos 50
#
# -------------------------------------------------------------
alert_history_recent()
{
    local limit="${1:-50}"

    alert_history_init

    tail -n "$limit" "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Buscar por alerta
# -------------------------------------------------------------
alert_history_find()
{
    local id="$1"

    alert_history_init

    grep "|$id|" "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Buscar por ação
#
# OPEN
# ACK
# RESOLVE
# SUPPRESS
#
# -------------------------------------------------------------
alert_history_action()
{
    local action="$1"

    alert_history_init

    grep "|$action|" "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Limpar histórico
# -------------------------------------------------------------
alert_history_clear()
{
    alert_history_init

    > "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Exportar JSON
# -------------------------------------------------------------
alert_history_json()
{
    local limit="${1:-50}"

    alert_history_init

    echo "["
    local first=1

    tail -n "$limit" "$HISTORY_FILE" |
    while IFS="|" read -r timestamp action id level old new message
    do
        [ -z "$timestamp" ] && continue

        if [ "$first" -eq 0 ]; then
            echo ","
        fi

        first=0

cat <<EOF
{
 "timestamp":"$timestamp",
 "action":"$action",
 "id":"$id",
 "level":"$level",
 "old_state":"$old",
 "new_state":"$new",
 "message":"$message"
}
EOF
    done

    echo "]"
}

# -------------------------------------------------------------
# Estatística simples
# -------------------------------------------------------------
alert_history_stats()
{
    alert_history_init

cat <<EOF
{
 "total_events": $(wc -l < "$HISTORY_FILE"),
 "opens": $(grep -c "|OPEN|" "$HISTORY_FILE" 2>/dev/null || echo 0),
 "acks": $(grep -c "|ACK|" "$HISTORY_FILE" 2>/dev/null || echo 0),
 "resolves": $(grep -c "|RESOLVE|" "$HISTORY_FILE" 2>/dev/null || echo 0),
 "suppressed": $(grep -c "|SUPPRESS|" "$HISTORY_FILE" 2>/dev/null || echo 0)
}
EOF
}

# -------------------------------------------------------------
# Tempo de incidente
#
# Calcula diferença entre OPEN e RESOLVE
#
# -------------------------------------------------------------
alert_history_duration()
{
    local id="$1"

    local open_time
    local resolve_time

    open_time=$(grep "|OPEN|$id|" "$HISTORY_FILE" |
        head -1 |
        cut -d'|' -f1)

    resolve_time=$(grep "|RESOLVE|$id|" "$HISTORY_FILE" |
        tail -1 |
        cut -d'|' -f1)

    if [ -z "$open_time" ] ||
       [ -z "$resolve_time" ]
    then
        echo "0"
        return
    fi

    start=$(date -d "$open_time" +%s)
    end=$(date -d "$resolve_time" +%s)

    echo $((end-start))
}

# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------
case "$1" in

init)
    alert_history_init
;;

write)
    alert_history_write \
    "$2" "$3" "$4" "$5" "$6" "$7"
;;

recent)
    alert_history_recent "$2"
;;

find)
    alert_history_find "$2"
;;

action)
    alert_history_action "$2"
;;

json)
    alert_history_json "$2"
;;

stats)
    alert_history_stats
;;

duration)
    alert_history_duration "$2"
;;

clear)
    alert_history_clear
;;

*)
cat <<EOF

DSM Alert History

Uso:

 alert_history.sh init

 alert_history.sh write <ação> <id> <nível> <anterior> <novo> <mensagem>

 alert_history.sh recent [quantidade]

 alert_history.sh find <id>

 alert_history.sh action <ação>

 alert_history.sh json [quantidade]

 alert_history.sh stats

 alert_history.sh duration <id>

 alert_history.sh clear

EOF
;;
esac
