#!/usr/bin/env bash
set -e
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE="${DSM_ROOT}/dashboard/state/health_state.json"

if [[ ! -f "$STATE" ]]
then
cat <<EOF
{
 "score":0,
 "status":"unknown"
}
EOF
exit 0
fi

cat "$STATE"
