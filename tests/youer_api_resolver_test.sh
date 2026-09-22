#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
PORT_FILE="${TMP}/port"

python3 - "${PORT_FILE}" <<'PY' &
import http.server, json, pathlib, socketserver, sys
port_file=pathlib.Path(sys.argv[1])
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        base=f"http://127.0.0.1:{self.server.server_address[1]}"
        if self.path == "/api/v2/projects/youer":
            body=json.dumps({"project":"youer","versions":["1.21.1","1.21.11","26.1","26.2"]}).encode()
        elif self.path == "/api/v2/projects/youer/1.21.1/builds":
            body=json.dumps({"builds":[
                {"number":656,"url":base+"/api/v2/projects/youer/1.21.1/builds/656/download"},
                {"number":657,"url":base+"/api/v2/projects/youer/1.21.1/builds/657/download"}
            ]}).encode()
        elif self.path == "/api/v2/projects/youer/1.21.11/builds":
            self.send_response(503);self.end_headers();return
        elif self.path == "/legacy/1.21.11/builds":
            body=json.dumps([
                {"id":18},
                {"id":19}
            ]).encode()
        elif self.path == "/api/v2/projects/youer/26.1/builds":
            body=json.dumps({"builds":[
                {"number":3,"url":base+"/api/v2/projects/youer/26.1/builds/3/download"}
            ]}).encode()
        elif self.path == "/api/v2/projects/youer/26.2/builds":
            self.send_response(503);self.end_headers();return
        elif self.path == "/legacy/26.2/builds":
            self.send_response(503);self.end_headers();return
        elif self.path.endswith("/download"):
            body=b"fake-jar"
            self.send_response(200)
            self.send_header("Content-Type","application/java-archive")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        else:
            self.send_response(404);self.end_headers();return
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args): pass
with socketserver.TCPServer(("127.0.0.1",0),Handler) as server:
    port_file.write_text(str(server.server_address[1]))
    server.serve_forever()
PY
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true; rm -rf -- "${TMP}"' EXIT
for _ in $(seq 1 50); do [[ -s "${PORT_FILE}" ]] && break; sleep 0.05; done
PORT="$(cat "${PORT_FILE}")"

export YOUER_API_BASE="http://127.0.0.1:${PORT}/api/v2/projects/youer"
export YOUER_LEGACY_API_BASE="http://127.0.0.1:${PORT}/legacy"
export YOUER_DISCOVERY_LIMIT=25
source "${ROOT}/installer/version_resolvers/youer_api.sh"

LIST="$(version_resolver_execute list minecraft youer '')"
jq -e '
  .variant=="youer"
  and .source=="mohistmc-api-v2"
  and ([.versions[].version] | unique | sort) == ["1.21.1","1.21.11","26.1","26.2"]
  and ([.versions[] | select(.version=="26.1" and .build=="3")] | length)==1
  and ([.versions[] | select(.version=="1.21.11" and .build=="19")] | length)==1
' <<<"${LIST}" >/dev/null

LATEST="$(version_resolver_execute resolve minecraft youer latest)"
jq -e '.version=="26.2" and .build=="latest" and .provider=="http" and .selected_asset.name=="server.jar" and (.selected_asset.url|endswith("/26.2/builds/latest/download"))' <<<"${LATEST}" >/dev/null

PINNED="$(version_resolver_execute resolve minecraft youer '1.21.11@18')"
jq -e '.version=="1.21.11" and .build=="18" and (.install.url|endswith("/legacy/1.21.11/builds/18/download"))' <<<"${PINNED}" >/dev/null

if version_resolver_execute resolve minecraft youer '1.20.6' >/dev/null 2>&1; then
  echo "FAIL: unpublished Youer version was accepted" >&2
  exit 1
fi

if version_resolver_execute resolve minecraft youer '1.21.1@999' >/dev/null 2>&1; then
  echo "FAIL: unknown Youer build was accepted" >&2
  exit 1
fi

echo "Youer API resolver tests passed."
