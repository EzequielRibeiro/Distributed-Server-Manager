#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
PORT_FILE="${TMP}/port"

python3 - "${PORT_FILE}" <<'PY' &
import http.server, json, pathlib, socketserver, sys
port_file=pathlib.Path(sys.argv[1])
manifest={
    "latest":{"release":"1.21.11","snapshot":"26w01a"},
    "versions":[
        {"id":"1.21.11","type":"release","url":None},
        {"id":"1.21.10","type":"release","url":None},
        {"id":"26w01a","type":"snapshot","url":None},
    ],
}
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        base=f"http://127.0.0.1:{self.server.server_address[1]}"
        if self.path == "/manifest.json":
            body=json.dumps({
                **manifest,
                "versions":[
                    {**manifest["versions"][0],"url":base+"/1.21.11.json"},
                    {**manifest["versions"][1],"url":base+"/1.21.10.json"},
                    {**manifest["versions"][2],"url":base+"/26w01a.json"},
                ],
            }).encode()
        elif self.path == "/1.21.11.json":
            body=json.dumps({"downloads":{"server":{"url":base+"/server-1.21.11.jar","sha1":"abc123","size":12345}}}).encode()
        elif self.path == "/1.21.10.json":
            body=json.dumps({"downloads":{"server":{"url":base+"/server-1.21.10.jar","sha1":"def456","size":12000}}}).encode()
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

export MINECRAFT_JAVA_MANIFEST_URL="http://127.0.0.1:${PORT}/manifest.json"
export MINECRAFT_JAVA_DISCOVERY_LIMIT=50
source "${ROOT}/installer/version_resolvers/minecraft_java.sh"

LIST="$(version_resolver_execute list minecraft vanilla '')"
jq -e '.variant=="vanilla" and (.versions|length)==2 and .versions[0].version=="1.21.11" and .versions[0].recommended==true and all(.versions[]; .version!="26w01a")' <<<"${LIST}" >/dev/null

LATEST="$(version_resolver_execute resolve minecraft vanilla latest)"
jq -e '.version=="1.21.11" and .build=="1.21.11" and .provider=="http" and .selected_asset.name=="server.jar" and .selected_asset.sha1=="abc123" and .selected_asset.size_bytes==12345 and (.selected_asset.url|endswith("/server-1.21.11.jar"))' <<<"${LATEST}" >/dev/null

PINNED="$(version_resolver_execute resolve minecraft vanilla 1.21.10)"
jq -e '.version=="1.21.10" and (.install.url|endswith("/server-1.21.10.jar"))' <<<"${PINNED}" >/dev/null

if version_resolver_execute resolve minecraft vanilla 1.20.1 >/dev/null 2>&1; then
  echo "FAIL: unknown Minecraft Java release was accepted" >&2
  exit 1
fi

echo "Minecraft Java Vanilla resolver tests passed."
