#!/usr/bin/env bash

set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
ACTION="${1:-}"
INSTANCE_PATH="${2:-}"

case "${ACTION}" in
    start|stop|restart|status)
        ;;
    *)
        printf '%s\n' '{"error":"invalid instance action"}' >&2
        exit 2
        ;;
esac

if [[ -z "${INSTANCE_PATH}" ]]
then
    printf '%s\n' '{"error":"instance path is required"}' >&2
    exit 3
fi

# Instance lifecycle is Agent-owned.  The Controller must never manipulate a
# local process as a compatibility fallback, even when the selected Agent is
# installed on the same host.  This bridge queues the command in the Controller
# database and waits for the owning Agent to report the final result.
exec python3 \
    "${DSM_ROOT}/dashboard/instance_runtime_command.py" \
    "${ACTION}" \
    "${INSTANCE_PATH}"
