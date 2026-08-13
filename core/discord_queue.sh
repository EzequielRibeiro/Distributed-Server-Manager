#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
#
# Arquivo:
#   core/discord_queue.sh
#
# Função:
#   Gerenciamento da fila de mensagens Discord
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

QUEUE_DIR="$DSM_ROOT/runtime/discord"
QUEUE_FILE="$QUEUE_DIR/queue.json"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
queue_init()
{
    mkdir -p "$QUEUE_DIR"

    if [ ! -f "$QUEUE_FILE" ]; then
        echo "[]" > "$QUEUE_FILE"
    fi
}

# -------------------------------------------------------------
# Adicionar mensagem na fila
# -------------------------------------------------------------
queue_add()
{
    local type="$1"
    local payload="$2"

    queue_init

    local tmp
    tmp=$(mktemp)

    jq \
    --arg type "$type" \
    --arg payload "$payload" \
    --arg id "$(uuidgen)" \
    --arg time "$(date -Iseconds)" \
'
.
+
[
 {
   "id":$id,
   "type":$type,
   "payload":$payload,
   "created":$time,
   "status":"PENDING"
 }
]
' \
"$QUEUE_FILE" > "$tmp"

    mv "$tmp" "$QUEUE_FILE"

    queue_limit
}

# -------------------------------------------------------------
# Limitar tamanho da fila
# -------------------------------------------------------------
queue_limit()
{
    local limit=100

    local count
    count=$(jq length "$QUEUE_FILE")

    if [ "$count" -gt "$limit" ]; then

        local tmp
        tmp=$(mktemp)

        jq \
        ".[-$limit:]" \
        "$QUEUE_FILE" \
        > "$tmp"

        mv "$tmp" "$QUEUE_FILE"
    fi
}

# -------------------------------------------------------------
# Listar pendentes
# -------------------------------------------------------------
queue_pending()
{
    queue_init

    jq '
    [
      .[]
      |
      select(.status=="PENDING")
    ]
    ' \
    "$QUEUE_FILE"
}

# -------------------------------------------------------------
# Buscar primeiro item
# -------------------------------------------------------------
queue_next()
{
    queue_pending \
    |
    jq '.[0]'
}

# -------------------------------------------------------------
# Marcar enviado
# -------------------------------------------------------------
queue_sent()
{
    local id="$1"

    local tmp
    tmp=$(mktemp)

    jq \
    --arg id "$id" \
'
map(
 if .id==$id
 then
   .status="SENT"
   | .sent_at=(now|todate)
 else
   .
 end
)
' \
"$QUEUE_FILE" \
> "$tmp"

    mv "$tmp" "$QUEUE_FILE"
}

# -------------------------------------------------------------
# Remover enviados antigos
# -------------------------------------------------------------
queue_cleanup()
{
    local tmp
    tmp=$(mktemp)

    jq '
    [
      .[]
      |
      select(.status!="SENT")
    ]
    ' \
    "$QUEUE_FILE" \
    > "$tmp"

    mv "$tmp" "$QUEUE_FILE"
}

# -------------------------------------------------------------
# Estatísticas
# -------------------------------------------------------------
queue_stats()
{
cat <<EOF

{
 "total": $(jq length "$QUEUE_FILE"),
 "pending":
 $(jq '[.[]|select(.status=="PENDING")]|length' "$QUEUE_FILE"),

 "sent":
 $(jq '[.[]|select(.status=="SENT")]|length' "$QUEUE_FILE")
}

EOF
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
case "$1" in

add)
    queue_add \
    "$2" \
    "$3"
;;

pending)
    queue_pending
;;

next)
    queue_next
;;

sent)
    queue_sent "$2"
;;

cleanup)
    queue_cleanup
;;

stats)
    queue_stats
;;

*)
cat <<EOF


DSM Discord Queue v1.2.0


Uso:


Adicionar:

 discord_queue.sh add TYPE PAYLOAD



Listar:

 discord_queue.sh pending



Próximo:

 discord_queue.sh next



Marcar enviado:

 discord_queue.sh sent ID



Limpar:

 discord_queue.sh cleanup



Estatísticas:

 discord_queue.sh stats



EOF
;;
esac
