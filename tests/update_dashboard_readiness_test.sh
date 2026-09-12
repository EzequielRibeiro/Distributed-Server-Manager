#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/update.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

INSTALL_DIR="${TMP}/dsm"
mkdir -p "${INSTALL_DIR}/bin" "${INSTALL_DIR}/database" "${INSTALL_DIR}/dashboard/config"

cat >"${INSTALL_DIR}/bin/cap" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${INSTALL_DIR}/bin/cap"

cat >"${INSTALL_DIR}/database/manager.py" <<'PY'
#!/usr/bin/env python3
raise SystemExit(0)
PY
chmod +x "${INSTALL_DIR}/database/manager.py"

RESTORE_SERVICES=(dsm-dashboard.service)
DSM_DATABASE_DRIVER=sqlite
CAPTURE="${TMP}/dashboard-readiness.txt"

# A falha transitória inicial não deve poluir um update que termina saudável.
READINESS_TIMEOUT=2
READINESS_INTERVAL=0
CURL_COUNT="${TMP}/curl-count"
printf '0\n' >"${CURL_COUNT}"

curl() {
    local COUNT
    COUNT="$(cat "${CURL_COUNT}")"
    COUNT=$((COUNT + 1))
    printf '%s\n' "${COUNT}" >"${CURL_COUNT}"

    if [[ "${COUNT}" -eq 1 ]]
    then
        echo "curl: (7) simulated transient failure" >&2
        return 7
    fi

    printf '%s\n' '{"status":"healthy"}'
    return 0
}

TRANSIENT_ERR="${TMP}/transient.err"

wait_for_dashboard_readiness \
    "https://127.0.0.1:9443/health" \
    "https" \
    2>"${TRANSIENT_ERR}"

[[ "$(cat "${CURL_COUNT}")" == "2" ]]
[[ ! -s "${TRANSIENT_ERR}" ]]

unset -f curl

# Uma falha persistente continua sendo erro e preserva o último diagnóstico.
READINESS_TIMEOUT=0

curl() {
    echo "curl: (7) simulated persistent failure" >&2
    return 7
}

PERSISTENT_ERR="${TMP}/persistent.err"

if wait_for_dashboard_readiness \
    "https://127.0.0.1:9443/health" \
    "https" \
    2>"${PERSISTENT_ERR}"
then
    PERSISTENT_RC=0
else
    PERSISTENT_RC=$?
fi

[[ "${PERSISTENT_RC}" -ne 0 ]]

grep -Fq     "Timeout aguardando Dashboard"     "${PERSISTENT_ERR}"

grep -Fq     "curl: (7) simulated persistent failure"     "${PERSISTENT_ERR}"

unset -f curl

wait_for_service_readiness() { :; }
wait_for_dashboard_readiness() {
    printf '%s|%s\n' "$1" "$2" >"${CAPTURE}"
}

DSM_WEB_SCHEME=https
DSM_WEB_PORT=9443
validate_runtime_readiness >/dev/null
[[ "$(cat "${CAPTURE}")" == "https://127.0.0.1:9443/health|https" ]]

DSM_WEB_SCHEME=http
DSM_WEB_PORT=18080
validate_runtime_readiness >/dev/null
[[ "$(cat "${CAPTURE}")" == "http://127.0.0.1:18080/health|http" ]]

unset DSM_WEB_PORT
validate_runtime_readiness >/dev/null
[[ "$(cat "${CAPTURE}")" == "http://127.0.0.1:8080/health|http" ]]

printf 'update_dashboard_readiness_test: OK\n'
