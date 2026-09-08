#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(
    cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
    pwd
)"

SUPERVISOR="${ROOT}/dashboard/workers/worker.sh"
TMP="$(mktemp -d)"

cleanup()
{
    pkill -f "${TMP}/" 2>/dev/null || true
    rm -rf "${TMP}"
}

trap cleanup EXIT

create_fixture()
{
    local TARGET="$1"
    local FAIL_FIRST="${2:-0}"

    mkdir -p \
        "${TARGET}/dashboard/workers" \
        "${TARGET}/logs"

    local WORKER

    for WORKER in \
        dashboard_worker.sh \
        metrics_worker.sh \
        scheduler_worker.sh \
        monitor_worker.sh
    do
        if [[ "${WORKER}" == "dashboard_worker.sh" &&
              "${FAIL_FIRST}" == "1" ]]
        then
            cat > "${TARGET}/dashboard/workers/${WORKER}" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
        else
            cat > "${TARGET}/dashboard/workers/${WORKER}" <<'EOF'
#!/usr/bin/env bash
trap 'exit 0' INT TERM
while true
do
    sleep 1
done
EOF
        fi

        chmod +x \
            "${TARGET}/dashboard/workers/${WORKER}"
    done

    for WORKER in \
        automation_worker.py \
        hybrid_agent_worker.py
    do
        cat > "${TARGET}/dashboard/workers/${WORKER}" <<'EOF'
#!/usr/bin/env python3
import time

while True:
    time.sleep(1)
EOF
    done
}

test_controlled_sigterm_returns_zero()
{
    local FIXTURE="${TMP}/controlled"

    create_fixture "${FIXTURE}" 0

    DSM_ROOT="${FIXTURE}" \
        bash "${SUPERVISOR}" &

    local PID=$!

    sleep 1

    if ! kill -0 "${PID}" 2>/dev/null
    then
        echo "[FALHA] supervisor encerrou antes do SIGTERM"
        return 1
    fi

    kill -TERM "${PID}"

    set +e
    wait "${PID}"
    local RC=$?
    set -e

    if [[ "${RC}" -ne 0 ]]
    then
        echo "[FALHA] SIGTERM controlado retornou ${RC}"
        return 1
    fi

    if grep -q \
        'encerrou inesperadamente' \
        "${FIXTURE}/logs/dashboard_worker.log"
    then
        echo "[FALHA] shutdown foi classificado como falha"
        cat "${FIXTURE}/logs/dashboard_worker.log"
        return 1
    fi

    grep -q \
        'Shutdown controlado concluído' \
        "${FIXTURE}/logs/dashboard_worker.log"

    echo "[OK] SIGTERM controlado retorna 0"
}

test_child_failure_still_returns_nonzero()
{
    local FIXTURE="${TMP}/failure"

    create_fixture "${FIXTURE}" 1

    set +e
    DSM_ROOT="${FIXTURE}" \
        bash "${SUPERVISOR}"
    local RC=$?
    set -e

    if [[ "${RC}" -eq 0 ]]
    then
        echo "[FALHA] morte real de worker retornou sucesso"
        return 1
    fi

    grep -q \
        'encerrou inesperadamente' \
        "${FIXTURE}/logs/dashboard_worker.log"

    echo "[OK] falha real continua retornando não-zero"
}

test_controlled_sigterm_returns_zero
test_child_failure_still_returns_nonzero

echo "[OK] contrato de shutdown do worker validado"
