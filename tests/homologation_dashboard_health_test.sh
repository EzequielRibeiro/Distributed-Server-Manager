#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=tests/lib/homologation_dashboard_health.sh
source "${ROOT}/tests/lib/homologation_dashboard_health.sh"

TMP_DIR="$(mktemp -d)"
cleanup(){ rm -rf -- "${TMP_DIR}"; }
trap cleanup EXIT

fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

FAKE_BIN="${TMP_DIR}/bin"
mkdir -p "${FAKE_BIN}" "${TMP_DIR}/root/dashboard/config"
cat >"${FAKE_BIN}/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" >"${CURL_ARGS_FILE}"
printf '{"status":"healthy","ready":true}\n'
SH
chmod +x "${FAKE_BIN}/curl"
PATH="${FAKE_BIN}:${PATH}"
export PATH
export DSM_ROOT="${TMP_DIR}/root"
export CURL_ARGS_FILE="${TMP_DIR}/curl.args"

cat >"${DSM_ROOT}/dashboard/config/dashboard.conf" <<'CONF'
HOST=0.0.0.0
PORT=8080
CONF

# HTTPS: effective listener must come from DSM_WEB_PORT while hostname/scheme
# come from the public Controller URL. TLS verification is preserved because
# the probe uses --resolve instead of --insecure.
export DSM_CONTROLLER_PUBLIC_URL="https://controller.capivaradsm.com.br:9443"
export DSM_WEB_PORT="9443"
dsm_dashboard_health_probe "${TMP_DIR}/https.json"
grep -Fx -- '--resolve' "${CURL_ARGS_FILE}" >/dev/null || fail "HTTPS probe missing --resolve"
grep -Fx -- 'controller.capivaradsm.com.br:9443:127.0.0.1' "${CURL_ARGS_FILE}" >/dev/null || fail "HTTPS probe resolved wrong endpoint"
grep -Fx -- 'https://controller.capivaradsm.com.br:9443/health' "${CURL_ARGS_FILE}" >/dev/null || fail "HTTPS probe used wrong URL"
! grep -Fx -- '--insecure' "${CURL_ARGS_FILE}" >/dev/null || fail "HTTPS probe disabled certificate verification"

# HTTP: no public URL falls back to the legacy dashboard.conf port.
unset DSM_CONTROLLER_PUBLIC_URL DSM_WEB_PORT
dsm_dashboard_health_probe "${TMP_DIR}/http.json"
grep -Fx -- 'http://127.0.0.1:8080/health' "${CURL_ARGS_FILE}" >/dev/null || fail "HTTP fallback used wrong URL"
! grep -Fx -- '--resolve' "${CURL_ARGS_FILE}" >/dev/null || fail "loopback HTTP probe should not require --resolve"

# Public URL port is used when DSM_WEB_PORT is absent.
export DSM_CONTROLLER_PUBLIC_URL="https://controller.example.test:9444"
unset DSM_WEB_PORT
dsm_dashboard_health_probe "${TMP_DIR}/public-port.json"
grep -Fx -- 'controller.example.test:9444:127.0.0.1' "${CURL_ARGS_FILE}" >/dev/null || fail "public URL port was not honored"
grep -Fx -- 'https://controller.example.test:9444/health' "${CURL_ARGS_FILE}" >/dev/null || fail "public URL health target was not honored"

printf 'Dashboard homologation health tests passed.\n'
