#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap '[[ -n "${SERVER_PID:-}" ]] && kill "${SERVER_PID}" 2>/dev/null || true; rm -rf -- "${TMP}"' EXIT

mkdir -p "${TMP}/v2/purpur/1.21.11"
cat >"${TMP}/v2/purpur/index.json" <<'JSON'
{"project":"purpur","metadata":{"current":"1.21.11"},"versions":["1.21.10","1.21.11"]}
JSON
cat >"${TMP}/v2/purpur/1.21.11/index.json" <<'JSON'
{"project":"purpur","version":"1.21.11","builds":{"latest":"2568","all":["2567","2568"]}}
JSON

python3 - "${TMP}" <<'PY' &
import http.server, pathlib, socketserver, sys
root = pathlib.Path(sys.argv[1])
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(root), **kwargs)
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        target = root / path.lstrip('/')
        if target.is_dir():
            self.path = path.rstrip('/') + '/index.json'
        return super().do_GET()
    def log_message(self, *args):
        pass
with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
    print(server.server_address[1], flush=True)
    pathlib.Path(root / 'port').write_text(str(server.server_address[1]))
    server.serve_forever()
PY
SERVER_PID=$!
for _ in $(seq 1 100); do [[ -s "${TMP}/port" ]] && break; sleep 0.05; done
PORT="$(cat "${TMP}/port")"

export PURPUR_API_BASE="http://127.0.0.1:${PORT}/v2"
source "${ROOT}/installer/version_resolvers/purpur_api.sh"

LIST="$(version_resolver_execute list minecraft purpur '')"
jq -e '.variant=="purpur" and (.versions|length)==2 and .versions[0].version=="1.21.11"' <<<"${LIST}" >/dev/null

LATEST="$(version_resolver_execute resolve minecraft purpur '1.21.11')"
jq -e '.version=="1.21.11" and .build=="2568" and .provider=="http" and .selected_asset.name=="server.jar" and (.selected_asset.url|endswith("/purpur/1.21.11/2568/download"))' <<<"${LATEST}" >/dev/null

PINNED="$(version_resolver_execute resolve minecraft purpur '1.21.11@2567')"
jq -e '.build=="2567" and .install.asset=="server.jar"' <<<"${PINNED}" >/dev/null

if version_resolver_execute resolve minecraft purpur '1.21.11@9999' >/dev/null 2>&1; then
  echo "FAIL: unknown Purpur build was accepted" >&2
  exit 1
fi

echo "Purpur API resolver tests passed."
