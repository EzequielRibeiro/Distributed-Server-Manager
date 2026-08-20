#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

exec python3 "${DSM_ROOT}/dashboard/infrastructure_doctor_api.py"
