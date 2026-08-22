#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
mkdir -p "${TMP}/scheduler" "${TMP}/cache" "${TMP}/logs"
cp "${ROOT}/scheduler/jobs.sh" "${ROOT}/scheduler/cron_engine.sh" "${ROOT}/scheduler/executor.sh" "${ROOT}/scheduler/history.sh" "${ROOT}/scheduler/scheduler.sh" "${ROOT}/scheduler/cli.sh" "${TMP}/scheduler/"
export DSM_ROOT="${TMP}"

bash "${TMP}/scheduler/cli.sh" create --name nightly --schedule 03:00 --command true
bash "${TMP}/scheduler/cli.sh" create --name heartbeat --schedule @every:300 --command true
bash "${TMP}/scheduler/cli.sh" create --name weekly --schedule @weekly --command true --disabled

jq -e '.jobs|length==3' "${TMP}/scheduler/jobs.db" >/dev/null
jq -e '.jobs[]|select(.name=="nightly" and .enabled==1 and .schedule=="03:00")' "${TMP}/scheduler/jobs.db" >/dev/null
jq -e '.jobs[]|select(.name=="weekly" and .enabled==0)' "${TMP}/scheduler/jobs.db" >/dev/null

bash "${TMP}/scheduler/cli.sh" update nightly --schedule 04:30 --command 'printf scheduler-ok'
bash "${TMP}/scheduler/cli.sh" disable nightly
jq -e '.jobs[]|select(.name=="nightly" and .enabled==0 and .schedule=="04:30")' "${TMP}/scheduler/jobs.db" >/dev/null
bash "${TMP}/scheduler/cli.sh" enable nightly

# @daily and the other symbolic schedules must be accepted by the jobs layer.
bash "${TMP}/scheduler/cli.sh" create --name daily --schedule @daily --command true

# Manual execution updates durable run metadata.
bash "${TMP}/scheduler/cli.sh" run heartbeat
jq -e '.jobs[]|select(.name=="heartbeat" and .last_status=="success" and .last_run_at!=null)' "${TMP}/scheduler/jobs.db" >/dev/null

# Disabled jobs are protected unless explicitly forced.
if bash "${TMP}/scheduler/cli.sh" run weekly 2>/dev/null; then
    echo "FAIL: disabled scheduler job ran without --force" >&2
    exit 1
fi
bash "${TMP}/scheduler/cli.sh" run weekly --force

bash "${TMP}/scheduler/cli.sh" delete daily
! jq -e '.jobs[]|select(.name=="daily")' "${TMP}/scheduler/jobs.db" >/dev/null

bash "${TMP}/scheduler/cli.sh" list --json | jq -e '.jobs|length==3' >/dev/null

echo "Scheduler management tests passed."
