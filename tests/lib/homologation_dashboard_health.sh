#!/usr/bin/env bash
# Shared dashboard health probe for destructive update homologation.
# The caller is expected to have sourced /opt/dsm/config/dsm.conf already.

_dsm_dashboard_public_origin() {
    local public_url="${DSM_CONTROLLER_PUBLIC_URL:-}"
    [[ -n "${public_url}" ]] || return 0
    python3 - "${public_url}" <<'PY'
from urllib.parse import urlsplit
import sys

value = sys.argv[1].strip()
try:
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    port = parsed.port or ""
except ValueError:
    raise SystemExit(2)
if scheme not in {"http", "https"} or not host:
    raise SystemExit(2)
print(scheme)
print(host)
print(port)
PY
}

_dsm_dashboard_legacy_port() {
    local root="${DSM_ROOT:-/opt/dsm}"
    local config="${root}/dashboard/config/dashboard.conf"
    [[ -r "${config}" ]] || return 0
    awk -F= '$1 == "PORT" {gsub(/[^0-9]/, "", $2); print $2; exit}' "${config}"
}

dsm_dashboard_health_probe() {
    local output_path="$1"
    local scheme="http"
    local host="127.0.0.1"
    local public_port=""
    local port="${DSM_WEB_PORT:-}"
    local -a origin=()
    local -a curl_args=(--fail --silent --show-error --max-time 10)

    if [[ -n "${DSM_CONTROLLER_PUBLIC_URL:-}" ]]
    then
        mapfile -t origin < <(_dsm_dashboard_public_origin) \
            || { printf 'invalid DSM_CONTROLLER_PUBLIC_URL\n' >&2; return 2; }
        scheme="${origin[0]:-http}"
        host="${origin[1]:-127.0.0.1}"
        public_port="${origin[2]:-}"
    fi

    [[ "${port}" =~ ^[0-9]+$ ]] || port=""
    if [[ -z "${port}" && "${public_port}" =~ ^[0-9]+$ ]]
    then
        port="${public_port}"
    fi
    if [[ -z "${port}" ]]
    then
        port="$(_dsm_dashboard_legacy_port)"
    fi
    [[ "${port}" =~ ^[0-9]+$ ]] || port=""
    if [[ -z "${port}" ]]
    then
        if [[ "${scheme}" == "https" ]]; then port="443"; else port="8080"; fi
    fi

    if [[ "${host}" != "127.0.0.1" && "${host}" != "localhost" ]]
    then
        curl_args+=(--resolve "${host}:${port}:127.0.0.1")
    fi

    curl "${curl_args[@]}" \
        "${scheme}://${host}:${port}/health" \
        >"${output_path}" 2>&1
}
