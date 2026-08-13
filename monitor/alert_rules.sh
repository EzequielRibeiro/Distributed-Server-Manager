#!/bin/bash
# =============================================================
# DSM Alert Engine v1.2.0
# Arquivo: monitor/alert_rules.sh
# Função: Motor de regras dos alertas DSM
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
CONFIG_FILE="$DSM_ROOT/config/alerts.conf"
ALERT_MANAGER="$DSM_ROOT/monitor/alertmanager.sh"

# Carregar configuração
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

# -------------------------------------------------------------
# Utilitário
# -------------------------------------------------------------
now()
{
    date -Iseconds
}

# -------------------------------------------------------------
# Criar alerta
# -------------------------------------------------------------
rule_open()
{
    local id="$1"
    local level="$2"
    local message="$3"

    "$ALERT_MANAGER" create \
        "$id" \
        "$level" \
        "$message"
}

# -------------------------------------------------------------
# Resolver alerta
# -------------------------------------------------------------
rule_resolve()
{
    local id="$1"
    "$ALERT_MANAGER" resolve "$id"
}

# -------------------------------------------------------------
# CPU DayZ
# -------------------------------------------------------------
check_dayz_cpu()
{
    local value="$1"

    if [ "$value" -ge "$DAYZ_CPU_CRITICAL" ]
    then
        rule_open \
        "dayz-cpu" \
        "CRITICAL" \
        "CPU do processo DayZ em ${value}%"
    elif [ "$value" -ge "$DAYZ_CPU_WARNING" ]
    then
        rule_open \
        "dayz-cpu" \
        "WARNING" \
        "CPU do processo DayZ elevada ${value}%"
    else
        rule_resolve "dayz-cpu"
    fi
}

# -------------------------------------------------------------
# CPU Host
# -------------------------------------------------------------
check_host_cpu()
{
    local value="$1"

    if [ "$value" -ge "$HOST_CPU_CRITICAL" ]
    then
        rule_open \
        "host-cpu" \
        "CRITICAL" \
        "CPU do host crítica ${value}%"
    elif [ "$value" -ge "$HOST_CPU_WARNING" ]
    then
        rule_open \
        "host-cpu" \
        "WARNING" \
        "CPU do host elevada ${value}%"
    else
        rule_resolve "host-cpu"
    fi
}

# -------------------------------------------------------------
# Memória RAM
# -------------------------------------------------------------
check_memory()
{
    local value="$1"

    if [ "$value" -ge "$RAM_CRITICAL" ]
    then
        rule_open \
        "memory" \
        "CRITICAL" \
        "Memória RAM crítica ${value}%"
    elif [ "$value" -ge "$RAM_WARNING" ]
    then
        rule_open \
        "memory" \
        "WARNING" \
        "Uso de RAM elevado ${value}%"
    else
        rule_resolve "memory"
    fi
}

# -------------------------------------------------------------
# Disco
# Recebe espaço livre
# -------------------------------------------------------------
check_disk()
{
    local free="$1"

    if [ "$free" -le "$DISK_CRITICAL_FREE" ]
    then
        rule_open \
        "disk" \
        "CRITICAL" \
        "Espaço em disco crítico ${free}% livre"
    elif [ "$free" -le "$DISK_WARNING_FREE" ]
    then
        rule_open \
        "disk" \
        "WARNING" \
        "Pouco espaço em disco ${free}% livre"
    else
        rule_resolve "disk"
    fi
}

# -------------------------------------------------------------
# Temperatura
# -------------------------------------------------------------
check_temperature()
{
    local temp="$1"

    if [ "$temp" -ge "$TEMP_CRITICAL" ]
    then
        rule_open \
        "temperature" \
        "CRITICAL" \
        "Temperatura crítica ${temp}°C"
    elif [ "$temp" -ge "$TEMP_WARNING" ]
    then
        rule_open \
        "temperature" \
        "WARNING" \
        "Temperatura elevada ${temp}°C"
    else
        rule_resolve "temperature"
    fi
}

# -------------------------------------------------------------
# Servidor offline
# -------------------------------------------------------------
check_dayz_status()
{
    local status="$1"

    if [ "$status" != "ONLINE" ]
    then
        if [ "$DAYZ_OFFLINE_ALERT" = "true" ]
        then
            rule_open \
            "dayz-offline" \
            "CRITICAL" \
            "Servidor DayZ offline"
        fi
    else
        rule_resolve "dayz-offline"
    fi
}

# -------------------------------------------------------------
# Avaliação completa
# -------------------------------------------------------------
evaluate_all()
{
    local dayz_cpu="$1"
    local host_cpu="$2"
    local memory="$3"
    local disk="$4"
    local temperature="$5"
    local server="$6"

    check_dayz_cpu "$dayz_cpu"
    check_host_cpu "$host_cpu"
    check_memory "$memory"
    check_disk "$disk"
    check_temperature "$temperature"
    check_dayz_status "$server"
}

# -------------------------------------------------------------
# Execução direta
# -------------------------------------------------------------

# Executa o CLI somente quando este arquivo for chamado diretamente.
# Quando carregado via source por alert_engine.sh, apenas disponibiliza
# as funções acima.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
case "$1" in
dayz_cpu)
    check_dayz_cpu "$2"
;;
host_cpu)
    check_host_cpu "$2"
;;
memory)
    check_memory "$2"
;;
disk)
    check_disk "$2"
;;
temperature)
    check_temperature "$2"
;;
server)
    check_dayz_status "$2"
;;
all)
    evaluate_all \
    "$2" \
    "$3" \
    "$4" \
    "$5" \
    "$6" \
    "$7"
;;
*)
cat <<EOF

DSM Alert Rules Engine

Uso:

 alert_rules.sh dayz_cpu <valor>

 alert_rules.sh host_cpu <valor>

 alert_rules.sh memory <valor>

 alert_rules.sh disk <valor>

 alert_rules.sh temperature <valor>

 alert_rules.sh server ONLINE|OFFLINE

Avaliação completa:

 alert_rules.sh all \
 <dayz_cpu> \
 <host_cpu> \
 <ram> \
 <disk_free> \
 <temperature> \
 <server_status>

EOF
;;
esac
fi
