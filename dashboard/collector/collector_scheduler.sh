#!/bin/bash
# DSM Dashboard Scheduler Collector

set -Eeuo pipefail
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
SCHEDULER_DIR="${DSM_ROOT}/scheduler"
STATE_DIR="${DSM_ROOT}/dashboard/state"
STATE_FILE="${STATE_DIR}/scheduler_state.json"
JOBS_DB="${SCHEDULER_DIR}/jobs.db"
HISTORY_FILE="${DSM_ROOT}/logs/scheduler_history.log"

init_state(){ mkdir -p "$STATE_DIR"; }

get_last_execution()
{
    if [ ! -f "$HISTORY_FILE" ]; then echo null; return; fi
    tail -1 "$HISTORY_FILE" | sed 's/^\[\(.*\)\].*/\1/' | jq -R .
}

count_jobs()
{
    [ -f "$JOBS_DB" ] || { echo 0; return; }
    jq '.jobs | length' "$JOBS_DB"
}

count_enabled()
{
    [ -f "$JOBS_DB" ] || { echo 0; return; }
    jq '[.jobs[] | select(.enabled==1 or .enabled==true)] | length' "$JOBS_DB"
}

next_execution()
{
    local schedule="$1" timezone_name="${2:-UTC}"
    if [ -x "${SCHEDULER_DIR}/cron_engine.sh" ]; then
        "${SCHEDULER_DIR}/cron_engine.sh" next-format "$schedule" "$timezone_name" 2>/dev/null || echo null
    else
        echo null
    fi
}

collect_jobs_summary()
{
    if [ ! -f "$JOBS_DB" ]; then echo '[]'; return; fi
    jq -c '.jobs[]' "$JOBS_DB" |
    while IFS= read -r job; do
        local_name=$(jq -r '.name' <<<"$job")
        local_schedule=$(jq -r '.schedule' <<<"$job")
        local_timezone=$(jq -r '.timezone // "UTC"' <<<"$job")
        local_enabled=$(jq -r '.enabled' <<<"$job")
        local_next=$(next_execution "$local_schedule" "$local_timezone")
        jq -n \
            --arg name "$local_name" \
            --arg schedule "$local_schedule" \
            --arg timezone "$local_timezone" \
            --arg next "$local_next" \
            --argjson enabled "$local_enabled" \
            '{name:$name,schedule:$schedule,timezone:$timezone,enabled:$enabled,next_run:$next}'
    done | jq -s .
}

collect_scheduler()
{
    init_state
    local total active last jobs
    total=$(count_jobs)
    active=$(count_enabled)
    last=$(get_last_execution)
    jobs=$(collect_jobs_summary)
    jq -n \
        --argjson total "$total" \
        --argjson active "$active" \
        --argjson last "$last" \
        --argjson jobs "$jobs" \
        '{module:"scheduler",status:"ONLINE",updated_at:(now|todate),jobs_total:$total,jobs_active:$active,last_execution:$last,jobs:$jobs}' \
        > "$STATE_FILE"
}

case "${1:-}" in
run) collect_scheduler ;;
status) cat "$STATE_FILE" ;;
*)
cat <<EOF
DSM Scheduler Collector

Uso:
collector_scheduler.sh run
collector_scheduler.sh status
EOF
;;
esac
