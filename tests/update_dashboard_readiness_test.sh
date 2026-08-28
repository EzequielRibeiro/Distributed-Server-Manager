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
cat >"${INSTALL_DIR}/dashboard/config/dashboard.conf" <<'CONF'
[DASHBOARD]
HOST=0.0.0.0
PORT=8181
CONF
validate_runtime_readiness >/dev/null
[[ "$(cat "${CAPTURE}")" == "http://127.0.0.1:8181/health|http" ]]

printf 'update_dashboard_readiness_test: OK\n'
