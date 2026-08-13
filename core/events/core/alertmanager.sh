#!/bin/bash
# =============================================================
# DSM Alert Manager v1.2.0
#
# Arquivo:
#   core/alertmanager.sh
#
# Função:
#   Motor central de decisão dos alertas DSM
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

NOTIFICATION_CENTER="$DSM_ROOT/core/notification_center.sh"
STATE_MANAGER="$DSM_ROOT/core/alert_state.sh"

HISTORY_FILE="$DSM_ROOT/runtime/alerts/history.json"
CONFIG_FILE="$DSM_ROOT/config/alerts.conf"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
alert_init()
{
    mkdir -p "$(dirname "$HISTORY_FILE")"

    if [ ! -f "$HISTORY_FILE" ]; then
        echo "[]" > "$HISTORY_FILE"
    fi
}

# -------------------------------------------------------------
# Carregar configuração
# -------------------------------------------------------------
load_config()
{
    if [ -f "$CONFIG_FILE" ]; then
        source "$CONFIG_FILE"
    fi
}

# -------------------------------------------------------------
# Registrar histórico
# -------------------------------------------------------------
history_add()
{
    local level="$1"
    local type="$2"
    local title="$3"
    local message="$4"

    local tmp
    tmp=$(mktemp)

    jq \
    --arg level "$level" \
    --arg type "$type" \
    --arg title "$title" \
    --arg message "$message" \
    --arg time "$(date -Iseconds)" \
'
.
+
[{
level:$level,
type:$type,
title:$title,
message:$message,
time:$time
}]
' \
"$HISTORY_FILE" > "$tmp"

    mv "$tmp" "$HISTORY_FILE"
}

# -------------------------------------------------------------
# Criar alerta
# -------------------------------------------------------------
fire_alert()
{
    local id="$1"
    local level="$2"
    local title="$3"
    local message="$4"

    alert_init

    "$STATE_MANAGER" create "$id"

    "$STATE_MANAGER" set \
        "$id" \
        ACTIVE

    "$NOTIFICATION_CENTER" create \
        "$id" \
        "$level" \
        "$title" \
        "$message"

    history_add \
        "$level" \
        "ALERT" \
        "$title" \
        "$message"
}

# -------------------------------------------------------------
# Resolver alerta
# -------------------------------------------------------------
resolve_alert()
{
    local id="$1"
    local title="$2"
    local message="$3"

    "$STATE_MANAGER" set \
        "$id" \
        RESOLVED

    "$NOTIFICATION_CENTER" resolve "$id"

    history_add \
        "OK" \
        "RECOVERY" \
        "$title" \
        "$message"
}

# -------------------------------------------------------------
# Regra CPU
# -------------------------------------------------------------
check_cpu()
{
    local cpu="$1"

    if [ "$cpu" -ge "$CPU_CRITICAL" ]; then
        fire_alert \
        "host-cpu" \
        "CRITICAL" \
        "CPU Host crítica" \
        "CPU em ${cpu}%"

    elif [ "$cpu" -ge "$CPU_WARNING" ]; then
        fire_alert \
        "host-cpu" \
        "WARNING" \
        "CPU elevada" \
        "CPU em ${cpu}%"

    else
        resolve_alert \
        "host-cpu" \
        "CPU normalizada" \
        "CPU voltou para ${cpu}%"
    fi
}

# -------------------------------------------------------------
# Regra memória
# -------------------------------------------------------------
check_memory()
{
    local mem="$1"

    if [ "$mem" -ge "$MEMORY_CRITICAL" ]; then
        fire_alert \
        "memory" \
        "CRITICAL" \
        "Memória crítica" \
        "RAM em ${mem}%"

    elif [ "$mem" -ge "$MEMORY_WARNING" ]; then
        fire_alert \
        "memory" \
        "WARNING" \
        "RAM elevada" \
        "RAM em ${mem}%"

    else
        resolve_alert \
        "memory" \
        "Memória normalizada" \
        "RAM em ${mem}%"
    fi
}

# -------------------------------------------------------------
# Regra disco
# -------------------------------------------------------------
check_disk()
{
    local free="$1"

    if [ "$free" -le "$DISK_CRITICAL" ]; then
        fire_alert \
        "disk" \
        "CRITICAL" \
        "Disco cheio" \
        "Espaço livre ${free}%"
    fi
}

# -------------------------------------------------------------
# Servidor DayZ
# -------------------------------------------------------------
check_server()
{
    local status="$1"

    if [ "$status" != "ONLINE" ]; then
        fire_alert \
        "dayz-server" \
        "CRITICAL" \
        "Servidor DayZ offline" \
        "Servidor não respondeu"

    else
        resolve_alert \
        "dayz-server" \
        "Servidor recuperado" \
        "DayZ online novamente"
    fi
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
case "$1" in

cpu)
    load_config
    check_cpu "$2"
;;

memory)
    load_config
    check_memory "$2"
;;

disk)
    load_config
    check_disk "$2"
;;

server)
    load_config
    check_server "$2"
;;

*)
cat <<EOF

DSM Alert Manager v1.2.0


Uso:


CPU:

 alertmanager.sh cpu <percentual>



Memória:

 alertmanager.sh memory <percentual>



Disco:

 alertmanager.sh disk <percentual>



Servidor:

 alertmanager.sh server ONLINE|OFFLINE



EOF
;;
esac
