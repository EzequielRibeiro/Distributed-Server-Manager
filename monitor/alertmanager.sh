#!/usr/bin/env bash
# =============================================================
# Capivara DSM Alert Manager v1.3.0
#
# Arquivo:
#   monitor/alertmanager.sh
#
# Função:
#   Fonte operacional única para o ciclo de vida dos alertas.
#
# Estados:
#   OPEN
#   ACKNOWLEDGED
#   RESOLVED
#   SUPPRESSED
#
# Runtime:
#   runtime/alerts/alerts.db
#   runtime/alerts/history.log
# =============================================================

set -u

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

ALERT_RUNTIME="${DSM_ROOT}/runtime/alerts"
ALERT_DB="${ALERT_RUNTIME}/alerts.db"
ALERT_HISTORY="${ALERT_RUNTIME}/history.log"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------

alertmanager_init()
{
    mkdir -p "$ALERT_RUNTIME"

    [ -f "$ALERT_DB" ] ||
        touch "$ALERT_DB"

    [ -f "$ALERT_HISTORY" ] ||
        touch "$ALERT_HISTORY"
}

# -------------------------------------------------------------
# Histórico
#
# Formato:
# timestamp|action|id|level|old_state|new_state|message
# -------------------------------------------------------------

alert_history()
{
    local action="$1"
    local id="$2"
    local level="$3"
    local old_state="$4"
    local new_state="$5"
    local message="$6"

    printf '%s|%s|%s|%s|%s|%s|%s\n' \
        "$(date -Iseconds)" \
        "$action" \
        "$id" \
        "$level" \
        "$old_state" \
        "$new_state" \
        "$message" \
        >> "$ALERT_HISTORY"
}

# -------------------------------------------------------------
# Buscar alerta
#
# alerts.db:
# id|state|level|timestamp|message
# -------------------------------------------------------------

alert_get()
{
    local id="$1"

    grep -F -m1 "${id}|" "$ALERT_DB" 2>/dev/null |
        awk -F'|' -v wanted="$id" '
            $1 == wanted {
                print
                exit
            }
        '
}

# -------------------------------------------------------------
# Estado atual
# -------------------------------------------------------------

alert_state()
{
    local id="$1"
    local current

    current="$(alert_get "$id")"

    [ -n "$current" ] || return 1

    printf '%s\n' "$current" |
        cut -d'|' -f2
}

# -------------------------------------------------------------
# Substituir registro de forma segura
# -------------------------------------------------------------

alert_replace()
{
    local id="$1"
    local record="$2"
    local tmp

    tmp="$(mktemp "${ALERT_RUNTIME}/alerts.db.XXXXXX")"

    awk -F'|' -v wanted="$id" '
        $1 != wanted
    ' "$ALERT_DB" > "$tmp"

    printf '%s\n' "$record" >> "$tmp"

    mv "$tmp" "$ALERT_DB"
}

# -------------------------------------------------------------
# Abrir / criar alerta
# -------------------------------------------------------------

alert_open()
{
    local id="$1"
    local level="$2"
    local message="$3"

    alertmanager_init

    local current
    current="$(alert_get "$id")"

    # ---------------------------------------------------------
    # Alerta ainda não existe
    # ---------------------------------------------------------
    if [ -z "$current" ]; then
        alert_replace \
            "$id" \
            "$id|OPEN|$level|$(date -Iseconds)|$message"

        alert_history \
            "OPEN" \
            "$id" \
            "$level" \
            "" \
            "OPEN" \
            "$message"

        return 0
    fi

    local old_state
    local old_level

    old_state="$(printf '%s\n' "$current" | cut -d'|' -f2)"
    old_level="$(printf '%s\n' "$current" | cut -d'|' -f3)"

    # ---------------------------------------------------------
    # Alerta resolvido/suprimido voltou a ocorrer
    # ---------------------------------------------------------
    if [ "$old_state" = "RESOLVED" ] ||
       [ "$old_state" = "SUPPRESSED" ]; then

        alert_replace \
            "$id" \
            "$id|OPEN|$level|$(date -Iseconds)|$message"

        alert_history \
            "REOPEN" \
            "$id" \
            "$level" \
            "$old_state" \
            "OPEN" \
            "$message"

        return 0
    fi

    # ---------------------------------------------------------
    # Escalonamento WARNING -> CRITICAL
    # ---------------------------------------------------------
    if [ "$level" = "CRITICAL" ] &&
       [ "$old_level" != "CRITICAL" ]; then

        alert_replace \
            "$id" \
            "$id|OPEN|CRITICAL|$(date -Iseconds)|$message"

        alert_history \
            "ESCALATE" \
            "$id" \
            "CRITICAL" \
            "$old_state" \
            "OPEN" \
            "$message"

        return 0
    fi

    # Alerta já está ativo no mesmo nível.
    # Não gera novo histórico para evitar spam.
    return 0
}

# -------------------------------------------------------------
# Reconhecer alerta
# -------------------------------------------------------------

alert_ack()
{
    local id="$1"
    local current
    local old_state
    local level
    local message

    current="$(alert_get "$id")"

    [ -n "$current" ] || return 1

    old_state="$(printf '%s\n' "$current" | cut -d'|' -f2)"
    level="$(printf '%s\n' "$current" | cut -d'|' -f3)"
    message="$(printf '%s\n' "$current" | cut -d'|' -f5-)"

    [ "$old_state" = "OPEN" ] || return 1

    alert_replace \
        "$id" \
        "$id|ACKNOWLEDGED|$level|$(date -Iseconds)|$message"

    alert_history \
        "ACK" \
        "$id" \
        "$level" \
        "$old_state" \
        "ACKNOWLEDGED" \
        "$message"
}

# -------------------------------------------------------------
# Resolver alerta
# -------------------------------------------------------------

alert_resolve()
{
    local id="$1"
    local current
    local old_state
    local level
    local message

    current="$(alert_get "$id")"

    # Resolver algo inexistente é idempotente.
    [ -n "$current" ] || return 0

    old_state="$(printf '%s\n' "$current" | cut -d'|' -f2)"

    # Já resolvido: nenhuma nova alteração.
    [ "$old_state" != "RESOLVED" ] || return 0

    level="$(printf '%s\n' "$current" | cut -d'|' -f3)"
    message="$(printf '%s\n' "$current" | cut -d'|' -f5-)"

    alert_replace \
        "$id" \
        "$id|RESOLVED|$level|$(date -Iseconds)|$message"

    alert_history \
        "RESOLVE" \
        "$id" \
        "$level" \
        "$old_state" \
        "RESOLVED" \
        "$message"
}

# -------------------------------------------------------------
# Suprimir alerta
# -------------------------------------------------------------

alert_suppress()
{
    local id="$1"
    local minutes="$2"
    local current
    local old_state
    local level
    local message
    local until

    [[ "$minutes" =~ ^[0-9]+$ ]] ||
        return 2

    [ "$minutes" -gt 0 ] ||
        return 2

    current="$(alert_get "$id")"

    [ -n "$current" ] || return 1

    old_state="$(printf '%s\n' "$current" | cut -d'|' -f2)"
    level="$(printf '%s\n' "$current" | cut -d'|' -f3)"
    message="$(printf '%s\n' "$current" | cut -d'|' -f5-)"

    until="$(
        date -d "+${minutes} minutes" -Iseconds
    )"

    alert_replace \
        "$id" \
        "$id|SUPPRESSED|$level|$until|$message"

    alert_history \
        "SUPPRESS" \
        "$id" \
        "$level" \
        "$old_state" \
        "SUPPRESSED" \
        "$message"
}

# -------------------------------------------------------------
# Listagem
# -------------------------------------------------------------

alert_list()
{
    cat "$ALERT_DB"
}

# -------------------------------------------------------------
# Contagem
# -------------------------------------------------------------

alert_count()
{
    local state="${1:-}"

    if [ -z "$state" ]
    then
        wc -l < "$ALERT_DB"
        return
    fi

    awk -F'|' -v wanted="$state" '
        $2 == wanted {
            count++
        }
        END {
            print count + 0
        }
    ' "$ALERT_DB"
}

# -------------------------------------------------------------
# JSON
# -------------------------------------------------------------

alert_json()
{
    jq -Rn '
        [
            inputs
            | select(length > 0)
            | split("|")
            | {
                id: .[0],
                state: .[1],
                level: .[2],
                time: .[3],
                message: (.[4:] | join("|"))
            }
        ]
    ' < "$ALERT_DB"
}

# -------------------------------------------------------------
# Inicialização obrigatória para qualquer operação
# -------------------------------------------------------------

alertmanager_init

# -------------------------------------------------------------
# CLI
# -------------------------------------------------------------

case "${1:-}" in

create|open)
    [ "$#" -ge 4 ] || {
        echo "Uso: alertmanager.sh create <id> <nível> <mensagem>" >&2
        exit 2
    }

    alert_open "$2" "$3" "$4"
    ;;

get)
    [ "$#" -ge 2 ] || exit 2
    alert_get "$2"
    ;;

state)
    [ "$#" -ge 2 ] || exit 2
    alert_state "$2"
    ;;

list)
    alert_list
    ;;

json)
    alert_json
    ;;

count)
    alert_count "${2:-}"
    ;;

ack)
    [ "$#" -ge 2 ] || exit 2
    alert_ack "$2"
    ;;

resolve)
    [ "$#" -ge 2 ] || exit 2
    alert_resolve "$2"
    ;;

suppress)
    [ "$#" -ge 3 ] || exit 2
    alert_suppress "$2" "$3"
    ;;

init)
    ;;

*)
    cat <<'USAGE'
Capivara DSM Alert Manager v1.3.0

Uso:
 alertmanager.sh init
 alertmanager.sh create <id> <nível> <mensagem>
 alertmanager.sh open <id> <nível> <mensagem>
 alertmanager.sh get <id>
 alertmanager.sh state <id>
 alertmanager.sh list
 alertmanager.sh json
 alertmanager.sh count [estado]
 alertmanager.sh ack <id>
 alertmanager.sh resolve <id>
 alertmanager.sh suppress <id> <minutos>
USAGE

    exit 2
    ;;
esac
