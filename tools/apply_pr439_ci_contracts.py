#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def remove_once(path: Path, block: str, label: str) -> None:
    replace_once(path, block, "", label)


def update_dashboard_health_http() -> None:
    path = ROOT / "dashboard" / "server.py"
    replace_once(
        path,
        '        if path == "/health":\n            health = dashboard_health()\n            self.send_json(200 if health.get("status") == "healthy" else 503, health)\n            return\n',
        '        if path == "/health":\n            self.send_json(200, dashboard_health())\n            return\n',
        "public health response",
    )


def update_readiness_probe() -> None:
    path = ROOT / "update.sh"
    old = '''wait_for_dashboard_readiness() {
    local DASHBOARD_URL="$1"
    local DASHBOARD_SCHEME="${2:-http}"
    local DEADLINE=$((SECONDS + READINESS_TIMEOUT))
    local LAST_ERROR=""
    local -a CURL_ARGS=(--fail --silent --show-error --max-time 5)

    # The loopback readiness probe verifies that the HTTPS listener is alive,
    # not the public certificate identity. A public certificate normally does
    # not contain 127.0.0.1, so only this local probe skips hostname validation.
    if [[ "${DASHBOARD_SCHEME}" == "https" ]]
    then
        CURL_ARGS+=(--insecure)
    fi

    while true
    do
        # Transient startup failures are expected while the listener is being
        # created. Keep them out of successful update logs, but retain the last
        # curl error so a real timeout remains actionable.
        if LAST_ERROR="$(curl "${CURL_ARGS[@]}" "${DASHBOARD_URL}" 2>&1 >/dev/null)"
        then
            return 0
        fi

        if (( SECONDS >= DEADLINE ))
        then
            echo "[ERROR] Timeout aguardando Dashboard | waiting for Dashboard: ${DASHBOARD_URL}" >&2
            if [[ -n "${LAST_ERROR}" ]]
            then
                echo "[ERROR] Último erro curl | Last curl error: ${LAST_ERROR}" >&2
            fi
            return 1
        fi

        sleep "${READINESS_INTERVAL}"
    done
}
'''
    new = '''wait_for_dashboard_readiness() {
    local DASHBOARD_URL="$1"
    local DASHBOARD_SCHEME="${2:-http}"
    local DEADLINE=$((SECONDS + READINESS_TIMEOUT))
    local LAST_ERROR=""
    local RESPONSE=""
    local -a CURL_ARGS=(--silent --show-error --max-time 5)

    # The public health endpoint is diagnostic and always returns JSON. Update
    # readiness remains fail-closed by accepting only an explicit healthy state.
    # For HTTPS loopback probing, skip hostname validation because the public
    # certificate normally does not contain 127.0.0.1.
    if [[ "${DASHBOARD_SCHEME}" == "https" ]]
    then
        CURL_ARGS+=(--insecure)
    fi

    while true
    do
        if RESPONSE="$(curl "${CURL_ARGS[@]}" "${DASHBOARD_URL}" 2>&1)"
        then
            if python3 -c 'import json,sys; payload=json.load(sys.stdin); raise SystemExit(0 if str(payload.get("status") or "").lower() == "healthy" else 1)' <<<"${RESPONSE}" 2>/dev/null
            then
                return 0
            fi
            LAST_ERROR="Dashboard health is not healthy: ${RESPONSE}"
        else
            LAST_ERROR="${RESPONSE}"
        fi

        if (( SECONDS >= DEADLINE ))
        then
            echo "[ERROR] Timeout aguardando Dashboard | waiting for Dashboard: ${DASHBOARD_URL}" >&2
            if [[ -n "${LAST_ERROR}" ]]
            then
                echo "[ERROR] Último erro | Last error: ${LAST_ERROR}" >&2
            fi
            return 1
        fi

        sleep "${READINESS_INTERVAL}"
    done
}
'''
    replace_once(path, old, new, "database-backed dashboard readiness")


def update_readiness_test() -> None:
    path = ROOT / "tests" / "update_dashboard_readiness_test.sh"
    replace_once(
        path,
        '''    if [[ "${COUNT}" -eq 1 ]]
    then
        echo "curl: (7) simulated transient failure" >&2
        return 7
    fi

    return 0
''',
        '''    if [[ "${COUNT}" -eq 1 ]]
    then
        echo "curl: (7) simulated transient failure" >&2
        return 7
    fi

    printf '%s\\n' '{"status":"healthy"}'
    return 0
''',
        "healthy readiness mock",
    )
    replace_once(
        path,
        '''unset DSM_WEB_PORT
cat >"${INSTALL_DIR}/dashboard/config/dashboard.conf" <<'CONF'
[DASHBOARD]
HOST=0.0.0.0
PORT=8181
CONF
validate_runtime_readiness >/dev/null
[[ "$(cat "${CAPTURE}")" == "http://127.0.0.1:8181/health|http" ]]
''',
        '''unset DSM_WEB_PORT
validate_runtime_readiness >/dev/null
[[ "$(cat "${CAPTURE}")" == "http://127.0.0.1:8080/health|http" ]]
''',
        "retired dashboard.conf fallback test",
    )


def update_update_manager_test() -> None:
    path = ROOT / "tests" / "update_manager_test.sh"
    replace_once(
        path,
        '''grep -Fq 'start_worker dashboard_worker.sh' "${ROOT}/dashboard/workers/worker.sh" \\
    || fail "dashboard aggregate state worker is not started"
grep -Fq 'migrate_dashboard_worker_services' "${UPDATE}" \\
    || fail "legacy dashboard worker services are not migrated"
''',
        '''if grep -Eq 'start_worker (dashboard_worker|metrics_worker|monitor_worker)\\.sh' "${ROOT}/dashboard/workers/worker.sh"; then
    fail "retired dashboard state worker is still launched"
fi
if grep -Fq 'migrate_dashboard_worker_services' "${UPDATE}"; then
    fail "retired dashboard worker migration still exists"
fi
''',
        "retired worker assertions",
    )
    replace_once(
        path,
        '''for state_name in dashboard server metrics monitor doctor scheduler; do
    [[ -f "${STATE_ROOT}/dashboard/state/${state_name}_state.json" ]] \\
        || fail "missing initialized dashboard state: ${state_name}"
done
for retired_state in alerts events; do
    [[ ! -e "${STATE_ROOT}/dashboard/state/${retired_state}_state.json" ]] \\
        || fail "database-backed ${retired_state} state was recreated as JSON"
done
''',
        '''for state_name in doctor scheduler; do
    [[ -f "${STATE_ROOT}/dashboard/state/${state_name}_state.json" ]] \\
        || fail "missing initialized dashboard state: ${state_name}"
done
for retired_state in alerts events dashboard server metrics monitor; do
    [[ ! -e "${STATE_ROOT}/dashboard/state/${retired_state}_state.json" ]] \\
        || fail "retired ${retired_state} state was recreated as JSON"
done
''',
        "state initializer contract",
    )
    text = path.read_text(encoding="utf-8")
    start_marker = '''(
    source "${UPDATE}"
    SYSTEMD_DIR="${TMP_DIR}/migration-systemd"
'''
    end_marker = '''(
    source "${UPDATE}"
    CONFIG_FILE="${TMP_DIR}/versioned-dsm.conf"
'''
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise RuntimeError("legacy worker migration regression block not found")
    text = text[:start] + end_marker + text[end + len(end_marker):]
    path.write_text(text, encoding="utf-8")


def update_cli_contract() -> None:
    workflow = ROOT / ".github" / "workflows" / "cli-unification.yml"
    text = workflow.read_text(encoding="utf-8")
    text = text.replace("      - 'bin/dsm'\n", "")
    text = text.replace("          bash -n bin/dsm\n", "")
    workflow.write_text(text, encoding="utf-8")

    contract = ROOT / "tests" / "cli_public_contract_test.sh"
    replace_once(
        contract,
        '''grep -Fq "'dsm' foi descontinuado como CLI pública. Use 'cap'." "${ROOT}/bin/dsm"
grep -Fq 'exec "${DSM_ROOT}/bin/cap" "$@"' "${ROOT}/bin/dsm"
[[ -x "${ROOT}/bin/dsm-compat" ]]
''',
        '''[[ ! -e "${ROOT}/bin/dsm" ]]
[[ -x "${ROOT}/bin/dsm-compat" ]]
''',
        "public dsm alias retirement",
    )


def main() -> None:
    update_dashboard_health_http()
    update_readiness_probe()
    update_readiness_test()
    update_update_manager_test()
    update_cli_contract()
    print("PR439 CI contracts updated")


if __name__ == "__main__":
    main()
