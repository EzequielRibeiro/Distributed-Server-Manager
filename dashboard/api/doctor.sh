#!/bin/bash
# =============================================================
# dashboard/api/doctor.sh
#
# API Runtime Adapter
# DSM Dashboard
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

RUNTIME_FILE="${DSM_ROOT}/runtime/state/doctor.json"


if [[ ! -f "$RUNTIME_FILE" ]]
then
    echo '{"ok":false,"error":"doctor runtime unavailable"}'
    exit 1
fi


cat "$RUNTIME_FILE"
