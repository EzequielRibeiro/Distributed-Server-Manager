#!/bin/bash
# =============================================================
# DSM Notification Center v1.2.0
#
# Arquivo:
#   core/notification_center.sh
#
# Função:
#   Gerenciamento central das notificações DSM
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

NOTIFY_DIR="$DSM_ROOT/runtime/alerts"
NOTIFY_FILE="$NOTIFY_DIR/notifications.json"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
notification_init()
{
    mkdir -p "$NOTIFY_DIR"

    if [ ! -f "$NOTIFY_FILE" ]; then
        echo "[]" > "$NOTIFY_FILE"
    fi
}

# -------------------------------------------------------------
# Data atual
# -------------------------------------------------------------
notification_time()
{
    date -Iseconds
}

# -------------------------------------------------------------
# Criar notificação
# -------------------------------------------------------------
notification_create()
{
    local id="$1"
    local level="$2"
    local title="$3"
    local message="$4"

    notification_init

    local time
    time=$(notification_time)

    local tmp
    tmp=$(mktemp)

    jq \
    --arg id "$id" \
    --arg level "$level" \
    --arg title "$title" \
    --arg message "$message" \
    --arg time "$time" \
'
if any(.[]; .id==$id and .status=="ACTIVE")
then .
else
. + [{
"id":$id,
"level":$level,
"title":$title,
"message":$message,
"status":"ACTIVE",
"ack":false,
"created":$time,
"updated":$time
}]
end
' \
"$NOTIFY_FILE" > "$tmp"

    mv "$tmp" "$NOTIFY_FILE"
}

# -------------------------------------------------------------
# Resolver alerta
# -------------------------------------------------------------
notification_resolve()
{
    local id="$1"

    notification_init

    local tmp
    tmp=$(mktemp)

    jq \
    --arg id "$id" \
    --arg time "$(notification_time)" \
'
map(
 if .id==$id
 then
 .status="RESOLVED"
 | .updated=$time
 else .
 end
)
' \
"$NOTIFY_FILE" > "$tmp"

    mv "$tmp" "$NOTIFY_FILE"
}

# -------------------------------------------------------------
# Reconhecer alerta
# -------------------------------------------------------------
notification_ack()
{
    local id="$1"

    notification_init

    local tmp
    tmp=$(mktemp)

    jq \
    --arg id "$id" \
'
map(
 if .id==$id
 then
 .ack=true
 else .
 end
)
' \
"$NOTIFY_FILE" > "$tmp"

    mv "$tmp" "$NOTIFY_FILE"
}

# -------------------------------------------------------------
# Listar ativos
# -------------------------------------------------------------
notification_active()
{
    notification_init

    jq '
[
 .[]
 |
 select(.status=="ACTIVE")
]
' "$NOTIFY_FILE"
}

# -------------------------------------------------------------
# Listar histórico
# -------------------------------------------------------------
notification_history()
{
    notification_init
    cat "$NOTIFY_FILE"
}

# -------------------------------------------------------------
# Contagem
# -------------------------------------------------------------
notification_count()
{
    notification_init

    jq '
[
 .[]
 |
 select(.status=="ACTIVE")
]
|
length
' "$NOTIFY_FILE"
}

# -------------------------------------------------------------
# Limpeza
# -------------------------------------------------------------
notification_cleanup()
{
    notification_init

    local limit="${ALERT_HISTORY_LIMIT:-5000}"

    local tmp
    tmp=$(mktemp)

    jq \
    --argjson limit "$limit" \
'
sort_by(.created)
|
reverse
|
.[0:$limit]
' \
"$NOTIFY_FILE" > "$tmp"

    mv "$tmp" "$NOTIFY_FILE"
}

# -------------------------------------------------------------
# Execução manual
# -------------------------------------------------------------
case "$1" in

create)
notification_create \
"$2" \
"$3" \
"$4" \
"$5"
;;

resolve)
notification_resolve "$2"
;;

ack)
notification_ack "$2"
;;

active)
notification_active
;;

history)
notification_history
;;

count)
notification_count
;;

cleanup)
notification_cleanup
;;

*)
cat <<EOF

DSM Notification Center v1.2.0


Uso:


create:

 notification_center.sh create \
 <id> \
 <level> \
 <title> \
 <message>



resolve:

 notification_center.sh resolve <id>



ack:

 notification_center.sh ack <id>



active:

 notification_center.sh active



history:

 notification_center.sh history



count:

 notification_center.sh count


EOF
;;
esac
