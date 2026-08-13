#!/bin/bash
# =============================================================
# DSM Alert State Manager v1.2.0
#
# Arquivo:
#   core/alert_state.sh
#
# Função:
#   Controle do ciclo de vida dos alertas DSM
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

STATE_DIR="$DSM_ROOT/runtime/alerts"
STATE_FILE="$STATE_DIR/states.json"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
state_init()
{
    mkdir -p "$STATE_DIR"

    if [ ! -f "$STATE_FILE" ]; then
        echo "[]" > "$STATE_FILE"
    fi
}

# -------------------------------------------------------------
# Data
# -------------------------------------------------------------
state_time()
{
    date -Iseconds
}

# -------------------------------------------------------------
# Validar transição
# -------------------------------------------------------------
state_transition_allowed()
{
    local old="$1"
    local new="$2"

    case "$old:$new" in

        NEW:ACTIVE)
            return 0
        ;;

        ACTIVE:ACKNOWLEDGED)
            return 0
        ;;

        ACTIVE:RESOLVED)
            return 0
        ;;

        ACKNOWLEDGED:RESOLVED)
            return 0
        ;;

        RESOLVED:CLOSED)
            return 0
        ;;

        *)
            return 1
        ;;
    esac
}

# -------------------------------------------------------------
# Criar estado
# -------------------------------------------------------------
state_create()
{
    local id="$1"

    state_init

    local tmp
    tmp=$(mktemp)

    jq \
    --arg id "$id" \
    --arg time "$(state_time)" \
'
if any(.[];.id==$id)
then .
else
. + [{
"id":$id,
"state":"NEW",
"created":$time,
"updated":$time
}]
end
' \
"$STATE_FILE" > "$tmp"

    mv "$tmp" "$STATE_FILE"
}

# -------------------------------------------------------------
# Alterar estado
# -------------------------------------------------------------
state_set()
{
    local id="$1"
    local new_state="$2"

    state_init

    local current
    current=$(jq -r \
    --arg id "$id" \
    '.[] | select(.id==$id) | .state' \
    "$STATE_FILE")

    if [ -z "$current" ]; then
        echo "Estado inexistente: $id"
        return 1
    fi

    if ! state_transition_allowed \
        "$current" \
        "$new_state"
    then
        echo "Transição inválida:"
        echo "$current -> $new_state"
        return 1
    fi

    local tmp
    tmp=$(mktemp)

    jq \
    --arg id "$id" \
    --arg state "$new_state" \
    --arg time "$(state_time)" \
'
map(
 if .id==$id
 then
 .state=$state
 |
 .updated=$time
 else .
 end
)
' \
"$STATE_FILE" > "$tmp"

    mv "$tmp" "$STATE_FILE"
}

# -------------------------------------------------------------
# Consultar estado
# -------------------------------------------------------------
state_get()
{
    local id="$1"

    state_init

    jq \
    --arg id "$id" \
'
.[] | select(.id==$id)
' \
"$STATE_FILE"
}

# -------------------------------------------------------------
# Listar estados
# -------------------------------------------------------------
state_list()
{
    state_init
    cat "$STATE_FILE"
}

# -------------------------------------------------------------
# Remover fechado
# -------------------------------------------------------------
state_cleanup()
{
    state_init

    local tmp
    tmp=$(mktemp)

    jq '
map(select(.state!="CLOSED"))
' \
"$STATE_FILE" > "$tmp"

    mv "$tmp" "$STATE_FILE"
}

# -------------------------------------------------------------
# Execução manual
# -------------------------------------------------------------
case "$1" in

create)
    state_create "$2"
;;

set)
    state_set "$2" "$3"
;;

get)
    state_get "$2"
;;

list)
    state_list
;;

cleanup)
    state_cleanup
;;

*)
cat <<EOF

DSM Alert State Manager v1.2.0


Uso:


Criar alerta:

 alert_state.sh create <id>



Alterar estado:

 alert_state.sh set <id> <estado>



Consultar:

 alert_state.sh get <id>



Listar:

 alert_state.sh list



Estados válidos:

 NEW
 ACTIVE
 ACKNOWLEDGED
 RESOLVED
 CLOSED


EOF
;;
esac
