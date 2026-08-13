#!/bin/bash
# =============================================================
# DSM Dashboard API - Scheduler
#
# Arquivo:
#   dashboard/api/scheduler.sh
#
# Responsável:
#   Expor dados do Scheduler para Dashboard
#
# DSM Version:
#   1.2.2
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
SCHEDULER_API="${DSM_ROOT}/scheduler/scheduler_api.sh"
CONTENT_TYPE="application/json"

# -------------------------------------------------------------
# Header HTTP
# -------------------------------------------------------------
echo "Content-Type: $CONTENT_TYPE"
echo ""

# -------------------------------------------------------------
# Validar API
# -------------------------------------------------------------
if [ ! -x "$SCHEDULER_API" ] && \
   [ ! -f "$SCHEDULER_API" ]
then
cat <<EOF
{
 "error":"scheduler_api.sh não encontrado"
}
EOF
exit 1
fi

# -------------------------------------------------------------
# Status Scheduler
# -------------------------------------------------------------
scheduler_status()
{
    local STATUS
    STATUS=$(bash "$SCHEDULER_API" status 2>/dev/null)

    if echo "$STATUS" | grep -q "ONLINE"
    then
        echo "online"
    else
        echo "offline"
    fi
}

# -------------------------------------------------------------
# Listar jobs JSON
# -------------------------------------------------------------
scheduler_jobs()
{
    local JOBS
    JOBS=$(bash "$SCHEDULER_API" list 2>/dev/null)

    if [ -z "$JOBS" ]
    then
        echo "[]"
        return
    fi

    echo "["

    local FIRST=1

    echo "$JOBS" | while read -r JOB
    do
        NAME=$(echo "$JOB" | jq -r '.name')
        SCHEDULE=$(echo "$JOB" | jq -r '.schedule')
        COMMAND=$(echo "$JOB" | jq -r '.command')
        ENABLED=$(echo "$JOB" | jq -r '.enabled')
        FILE=$(echo "$JOB" | jq -r '.file')

        NEXT=$(bash "$SCHEDULER_API" next "$SCHEDULE" 2>/dev/null)

        if [ "$FIRST" -eq 0 ]
        then
            echo ","
        fi

        FIRST=0

        jq -n \
        --arg name "$NAME" \
        --arg schedule "$SCHEDULE" \
        --arg command "$COMMAND" \
        --arg file "$FILE" \
        --arg next "$NEXT" \
        --argjson enabled "$ENABLED" \
        '
        {
            name:$name,
            schedule:$schedule,
            command:$command,
            enabled:$enabled,
            file:$file,
            next_run:$next
        }
        '
    done

    echo "]"
}

# -------------------------------------------------------------
# Resposta principal
# -------------------------------------------------------------
cat <<EOF
{
    "scheduler":{
        "status":"$(scheduler_status)",
        "jobs":
$(scheduler_jobs)
    }
}
EOF
