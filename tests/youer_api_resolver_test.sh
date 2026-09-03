#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT
mkdir -p "${TMP}/project/youer/1.21.1/builds/657"
cat >"${TMP}/project/youer/1.21.1/builds/index.json" <<'JSON'
[
  {"id":657},
  {"id":656}
]
JSON
printf 'fake-jar' >"${TMP}/project/youer/1.21.1/builds/657/download"

PORT_FILE="${TMP}/port"
python3 - "${TMP}" "${PORT_FILE}" <<'PY' &
import http.server, pathlib, socketserver, sys
root=pathlib.Path(sys.argv[1])
port_file=pathlib.Path(sys.argv[2])
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(root),**kwargs)
    def log_message(self,*args): pass
with socketserver.TCPServer(("127.0.0.1",0),Handler) as server:
    port_file.write_text(str(server.server_address[1]))
    server.serve_forever()
PY
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true; rm -rf -- "${TMP}"' EXIT
for _ in $(seq 1 50); do [[ -s "${PORT_FILE}" ]] && break; sleep 0.05; done
PORT="$(cat "${PORT_FILE}")"

# The fixture exposes the API list at the exact resolver path expected by Youer.
mkdir -p "${TMP}/project/youer/1.21.1"
cp "${TMP}/project/youer/1.21.1/builds/index.json" "${TMP}/project/youer/1.21.1/builds.json"

# Override curl-facing base with a tiny path adapter so /builds maps to builds.json.
ADAPTER="${TMP}/adapter"
mkdir -p "${ADAPTER}/project/youer/1.21.1/builds/657"
cp "${TMP}/project/youer/1.21.1/builds/index.json" "${ADAPTER}/project/youer/1.21.1/builds"
cp "${TMP}/project/youer/1.21.1/builds/657/download" "${ADAPTER}/project/youer/1.21.1/builds/657/download"
kill "${SERVER_PID}" 2>/dev/null || true
wait "${SERVER_PID}" 2>/dev/null || true
python3 - "${ADAPTER}" "${PORT_FILE}" <<'PY' &
import http.server, pathlib, socketserver, sys
root=pathlib.Path(sys.argv[1])
port_file=pathlib.Path(sys.argv[2])
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(root),**kwargs)
    def log_message(self,*args): pass
with socketserver.TCPServer(("127.0.0.1",0),Handler) as server:
    port_file.write_text(str(server.server_address[1]))
    server.serve_forever()
PY
SERVER_PID=$!
for _ in $(seq 1 50); do [[ -s "${PORT_FILE}" ]] && break; sleep 0.05; done
PORT="$(cat "${PORT_FILE}")"

export YOUER_API_BASE="http://127.0.0.1:${PORT}/project/youer"
source "${ROOT}/installer/version_resolvers/youer_api.sh"

LIST="$(version_resolver_execute list minecraft youer '')"
jq -e '.variant=="youer" and (.versions|length)==2 and .versions[0].version=="1.21.1"' <<<"${LIST}" >/dev/null

LATEST="$(version_resolver_execute resolve minecraft youer '1.21.1')"
jq -e '.version=="1.21.1" and .build=="657" and .provider=="http" and .selected_asset.name=="server.jar" and (.selected_asset.url|endswith("/1.21.1/builds/657/download"))' <<<"${LATEST}" >/dev/null

PINNED="$(version_resolver_execute resolve minecraft youer '1.21.1@656')"
jq -e '.build=="656" and .install.asset=="server.jar"' <<<"${PINNED}" >/dev/null

if version_resolver_execute resolve minecraft youer '1.21.11' >/dev/null 2>&1; then
  echo "FAIL: unsupported Youer version was accepted" >&2
  exit 1
fi

if version_resolver_execute resolve minecraft youer '1.21.1@999' >/dev/null 2>&1; then
  echo "FAIL: unknown Youer build was accepted" >&2
  exit 1
fi

echo "Youer API resolver tests passed."
