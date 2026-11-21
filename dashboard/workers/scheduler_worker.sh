#!/usr/bin/env bash

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_INTERVAL="${DSM_INTERVAL:-10}"

STATE_DIR="${DSM_ROOT}/dashboard/state"
OUTPUT="${STATE_DIR}/scheduler_state.json"

JOBS_DB="${DSM_ROOT}/scheduler/jobs.db"
HOLD_GATE="${WORKERS_DIR}/maintenance_hold_gate.py"


scheduler_update()
{
    mkdir -p "$STATE_DIR"

    local TOTAL=0
    local ENABLED=0
    local JOBS="[]"


    if [ -f "$JOBS_DB" ]
    then

        TOTAL=$(jq '.jobs | length' "$JOBS_DB")

        ENABLED=$(jq '
        [.jobs[] | select(.enabled==1)]
        | length
        ' "$JOBS_DB")

        JOBS=$(jq -c '.jobs' "$JOBS_DB")

    fi


cat > "$OUTPUT" <<EOF
{
    "module":"scheduler",
    "version":"1.2.2",
    "dashboard_version":"1.3.0",

    "status":"RUNNING",

    "jobs_total":$TOTAL,

    "jobs_active":$ENABLED,

    "jobs":$JOBS,

    "health":{
        "status":"OK",
        "message":"Scheduler Worker operacional"
    },

    "statistics":{
        "executed":0,
        "success":0,
        "failed":0
    },

    "updated_at":"$(date -Iseconds)"
}
EOF

}


main()
{
    while true
    do
        # Missing reader, unreadable/invalid marker or maintenance hold:
        # do not change scheduler state. This does not attest idle workers.
        # The common Python gate owns a flock during the entire single tick.
        if [[ -f "${HOLD_GATE}" ]]; then
            python3 -B "${HOLD_GATE}" --scheduler-tick || true
        fi
        sleep "$DSM_INTERVAL"
    done
}


if [[ "${1:-}" == "--once" ]]; then
    # Called by the gate while its flock is held; not a host-wide ACK.
    scheduler_update
else
    main
fi