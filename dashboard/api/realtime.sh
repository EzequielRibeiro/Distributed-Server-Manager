#!/usr/bin/env bash
set -e
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
REALTIME="${STATE_DIR}/realtime_state.json"

if [[ ! -f "$REALTIME" ]]
then
cat <<EOF
{
 "cpu":0,
 "memory":0,
 "players":0,
 "uptime":0,
 "timestamp":0
}
EOF
exit 0
fi

cat "$REALTIME"
