#!/bin/bash
# =============================================================
# DSM Dashboard Worker
# alerts_worker.sh
# Atualiza: dashboard/state/alerts_state.json
# Intervalo: 5 segundos
# =============================================================

set -euo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
METRICS="$STATE_DIR/metrics_state.json"
MONITOR="$STATE_DIR/monitor_state.json"
OUTPUT="$STATE_DIR/alerts_state.json"

mkdir -p "$STATE_DIR"

while true
do
    TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
    TMP=$(mktemp)
    echo "[]" > "$TMP"

    # ---------------------------------------------------------
    # Carrega métricas
    # ---------------------------------------------------------
    if [ -f "$METRICS" ]
    then
        CPU_DAYZ=$(jq -r '.cpu.process_pct // 0' "$METRICS")
        CPU_HOST=$(jq -r '.cpu.host_pct // 0' "$METRICS")
        RAM_HOST=$(jq -r '.memory.host_used_pct // 0' "$METRICS")
        TEMP=$(jq -r '.temperature.cpu_celsius // 0' "$METRICS")
        DISK=$(jq -r '.disk.free_pct // 100' "$METRICS")
    else
        CPU_DAYZ=0
        CPU_HOST=0
        RAM_HOST=0
        TEMP=0
        DISK=100
    fi

    # ---------------------------------------------------------
    # Estado do monitor
    # ---------------------------------------------------------
    if [ -f "$MONITOR" ]
    then
        HEALTH=$(jq -r '.health // "OK"' "$MONITOR")
        ONLINE=$(jq -r '.online // false' "$MONITOR")
    else
        HEALTH="DESCONHECIDO"
        ONLINE=false
    fi

    # ---------------------------------------------------------
    # Servidor Offline
    # ---------------------------------------------------------
    if [ "$ONLINE" != "true" ]
    then
        jq \
        '. += [{
            "level":"CRITICAL",
            "title":"Servidor Offline",
            "metric":"server",
            "message":"O servidor DayZ não está em execução.",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    fi

    # ---------------------------------------------------------
    # CPU DayZ
    # ---------------------------------------------------------
    CPU_INT=${CPU_DAYZ%.*}
    if (( CPU_INT >= 90 ))
    then
        LEVEL="CRITICAL"
    elif (( CPU_INT >= 70 ))
    then
        LEVEL="WARNING"
    else
        LEVEL=""
    fi

    if [ -n "$LEVEL" ]
    then
        jq \
        '. += [{
            "level":"'"$LEVEL"'",
            "title":"CPU DayZ Elevada",
            "metric":"cpu_dayz",
            "value":"'"$CPU_DAYZ"'%",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    fi

    # ---------------------------------------------------------
    # CPU Host
    # ---------------------------------------------------------
    CPU_INT=${CPU_HOST%.*}
    if (( CPU_INT >= 90 ))
    then
        LEVEL="CRITICAL"
    elif (( CPU_INT >= 75 ))
    then
        LEVEL="WARNING"
    else
        LEVEL=""
    fi

    if [ -n "$LEVEL" ]
    then
        jq \
        '. += [{
            "level":"'"$LEVEL"'",
            "title":"CPU Host Elevada",
            "metric":"cpu_host",
            "value":"'"$CPU_HOST"'%",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    fi

    # ---------------------------------------------------------
    # RAM
    # ---------------------------------------------------------
    RAM_INT=${RAM_HOST%.*}
    if (( RAM_INT >= 90 ))
    then
        LEVEL="CRITICAL"
    elif (( RAM_INT >= 80 ))
    then
        LEVEL="WARNING"
    else
        LEVEL=""
    fi

    if [ -n "$LEVEL" ]
    then
        jq \
        '. += [{
            "level":"'"$LEVEL"'",
            "title":"Memória do Host Elevada",
            "metric":"ram",
            "value":"'"$RAM_HOST"'%",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    fi

    # ---------------------------------------------------------
    # Disco
    # ---------------------------------------------------------
    DISK_INT=${DISK%.*}
    if (( DISK_INT <= 10 ))
    then
        LEVEL="CRITICAL"
    elif (( DISK_INT <= 20 ))
    then
        LEVEL="WARNING"
    else
        LEVEL=""
    fi

    if [ -n "$LEVEL" ]
    then
        jq \
        '. += [{
            "level":"'"$LEVEL"'",
            "title":"Pouco Espaço em Disco",
            "metric":"disk",
            "value":"'"$DISK"'%",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    fi

    # ---------------------------------------------------------
    # Temperatura
    # ---------------------------------------------------------
    TEMP_INT=${TEMP%.*}
    if (( TEMP_INT >= 85 ))
    then
        LEVEL="CRITICAL"
    elif (( TEMP_INT >= 70 ))
    then
        LEVEL="WARNING"
    else
        LEVEL=""
    fi

    if [ -n "$LEVEL" ]
    then
        jq \
        '. += [{
            "level":"'"$LEVEL"'",
            "title":"Temperatura Elevada",
            "metric":"temperature",
            "value":"'"$TEMP"'°C",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    fi

    # ---------------------------------------------------------
    # Saúde Geral
    # ---------------------------------------------------------
    if [ "$HEALTH" = "CRITICO" ]
    then
        jq \
        '. += [{
            "level":"CRITICAL",
            "title":"Estado Crítico",
            "metric":"health",
            "value":"CRITICO",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    elif [ "$HEALTH" = "DEGRADADO" ]
    then
        jq \
        '. += [{
            "level":"WARNING",
            "title":"Servidor Degradado",
            "metric":"health",
            "value":"DEGRADADO",
            "timestamp":"'"$TIMESTAMP"'"
        }]' \
        "$TMP" > "$TMP.new"
        mv "$TMP.new" "$TMP"
    fi

    # ---------------------------------------------------------
    # Salva estado
    # ---------------------------------------------------------
    jq -n \
        --arg ts "$TIMESTAMP" \
        --slurpfile alerts "$TMP" \
'{
    timestamp:$ts,
    count:($alerts[0]|length),
    alerts:$alerts[0]
}' > "$OUTPUT.tmp"
    mv "$OUTPUT.tmp" "$OUTPUT"
    rm -f "$TMP"
    sleep 5
done
