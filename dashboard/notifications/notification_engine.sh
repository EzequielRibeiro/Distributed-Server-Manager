#!/bin/bash
# =============================================================
# DSM Notification Engine
# Módulo 11.6
# Rules Engine: Analisa estados DSM, Gera notificações, Alimenta notification_queue.json
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="$DSM_ROOT/dashboard/state"
BASE="$DSM_ROOT/dashboard/notifications"
QUEUE="$BASE/notification_queue.json"

mkdir -p "$BASE"
if [ ! -f "$QUEUE" ]
then
    echo "[]" > "$QUEUE"
fi

# -------------------------------------------------------------
# Adicionar alerta na fila
# -------------------------------------------------------------
add_notification() {
    local LEVEL="$1"
    local TITLE="$2"
    local MESSAGE="$3"
    local ID="$4"

    EXIST=$(jq --arg id "$ID" 'map(select(.id==$id)) | length' "$QUEUE")
    if [ "$EXIST" -gt 0 ]
    then
        return
    fi

    TMP=$(mktemp)
    jq \
    --arg id "$ID" \
    --arg level "$LEVEL" \
    --arg title "$TITLE" \
    --arg message "$MESSAGE" \
    '. += [{ id:$id, level:$level, title:$title, message:$message, created_at:(now|todate), processed:false, sent:false }]' \
    "$QUEUE" > "$TMP"
    mv "$TMP" "$QUEUE"
}

# =============================================================
# SERVER STATE
# =============================================================
SERVER_STATE="$STATE_DIR/server_state.json"
if [ -f "$SERVER_STATE" ]
then
    ONLINE=$(jq -r '.online // false' "$SERVER_STATE")
    if [ "$ONLINE" != "true" ]
    then
        add_notification "CRITICAL" "Servidor DayZ Offline" "O servidor DayZ está parado ou indisponível." "server-offline"
    fi
fi

# =============================================================
# METRICS STATE
# =============================================================
METRICS_STATE="$STATE_DIR/metrics_state.json"
if [ -f "$METRICS_STATE" ]
then
    CPU=$(jq -r '.cpu.host_pct // 0' "$METRICS_STATE")
    RAM=$(jq -r '.memory.host_used_pct // 0' "$METRICS_STATE")
    DISK=$(jq -r '.disk.free_pct // 100' "$METRICS_STATE")

    CPU_INT=${CPU%.*}
    RAM_INT=${RAM%.*}
    DISK_INT=${DISK%.*}

    if [ "$CPU_INT" -ge 90 ]
    then
        add_notification "CRITICAL" "CPU Alta" "CPU do host acima de 90% ($CPU%)." "cpu-critical"
    elif [ "$CPU_INT" -ge 75 ]
    then
        add_notification "WARNING" "CPU Elevada" "CPU do host acima de 75% ($CPU%)." "cpu-warning"
    fi

    if [ "$RAM_INT" -ge 95 ]
    then
        add_notification "CRITICAL" "Memória Crítica" "Uso de RAM acima de 95% ($RAM%)." "ram-critical"
    elif [ "$RAM_INT" -ge 80 ]
    then
        add_notification "WARNING" "Memória Alta" "Uso de RAM acima de 80% ($RAM%)." "ram-warning"
    fi

    if [ "$DISK_INT" -le 10 ]
    then
        add_notification "CRITICAL" "Disco Cheio" "Espaço livre abaixo de 10% ($DISK%)." "disk-critical"
    elif [ "$DISK_INT" -le 20 ]
    then
        add_notification "WARNING" "Pouco Espaço em Disco" "Espaço livre abaixo de 20% ($DISK%)." "disk-warning"
    fi
fi

# =============================================================
# DOCTOR STATE
# =============================================================
DOCTOR_STATE="$STATE_DIR/doctor_state.json"
if [ -f "$DOCTOR_STATE" ]
then
    STATUS=$(jq -r '.status // "OK"' "$DOCTOR_STATE")
    if [ "$STATUS" != "OK" ]
    then
        add_notification "WARNING" "DSM Doctor encontrou problemas" "Diagnóstico retornou status $STATUS." "doctor-warning"
    fi
fi

# =============================================================
# SCHEDULER STATE
# =============================================================
SCHED_STATE="$STATE_DIR/scheduler_state.json"
if [ -f "$SCHED_STATE" ]
then
    FAILED=$(jq -r '.failed_jobs // 0' "$SCHED_STATE")
    if [ "$FAILED" -gt 0 ]
    then
        add_notification "WARNING" "Scheduler com falhas" "$FAILED tarefas falharam." "scheduler-failed"
    fi
fi

exit 0

