#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASKS_DIR="${ROOT}/scheduler/tasks"

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

[[ -d "${TASKS_DIR}" ]] || fail "scheduler tasks directory missing"

found=0

while IFS= read -r -d '' task
do
    found=1

    if grep -q $'\r' "${task}"
    then
        fail "CR/CRLF detected in ${task#${ROOT}/}"
    fi

    bash -n "${task}" \
        || fail "invalid shell syntax in ${task#${ROOT}/}"

done < <(
    find "${TASKS_DIR}" \
        -maxdepth 1 \
        -type f \
        -name '*.task' \
        -print0
)

[[ "${found}" -eq 1 ]] \
    || fail "no scheduler task files found"

grep -Eq '^\*\.task[[:space:]]+text[[:space:]]+eol=lf$' \
    "${ROOT}/.gitattributes" \
    || fail ".gitattributes does not enforce LF for *.task"

echo "Scheduler task line-ending tests passed."
