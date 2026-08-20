#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
STATE_DIR="${DSM_ROOT}/dashboard/state"
OUTPUT="${STATE_DIR}/doctor_state.json"
TMP="${OUTPUT}.tmp"

mkdir -p "${STATE_DIR}"

set +e
python3 "${DSM_ROOT}/database/infrastructure_doctor_contract.py" doctor --json > "${TMP}"
rc=$?
set -e

if python3 -m json.tool "${TMP}" >/dev/null 2>&1
then
    mv "${TMP}" "${OUTPUT}"
    exit 0
fi

rm -f "${TMP}"
exit "${rc:-1}"
