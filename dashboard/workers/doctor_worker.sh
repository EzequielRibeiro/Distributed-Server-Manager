#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
DSM_INTERVAL="${DSM_INTERVAL:-60}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
OUTPUT="${STATE_DIR}/doctor_state.json"
TMP="${OUTPUT}.tmp"

mkdir -p "${STATE_DIR}"

publish_doctor() {
    if python3 "${DSM_ROOT}/database/infrastructure_doctor_contract.py" doctor --json > "${TMP}"
    then
        mv "${TMP}" "${OUTPUT}"
        return 0
    fi

    # The Doctor intentionally exits non-zero when infrastructure is not ready.
    # A valid JSON payload is still useful to the Dashboard in that case.
    if python3 -m json.tool "${TMP}" >/dev/null 2>&1
    then
        mv "${TMP}" "${OUTPUT}"
        return 0
    fi

    rm -f "${TMP}"
    return 1
}

while true
do
    publish_doctor || true
    sleep "${DSM_INTERVAL}"
done
