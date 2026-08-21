#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT
mkdir -p "${TMP}/bin" "${TMP}/core" "${TMP}/agents/linux/runtime" "${TMP}/database"
cp "${ROOT}/bin/cap" "${TMP}/bin/cap"
cp "${ROOT}/core/role_context.py" "${TMP}/core/role_context.py"
chmod +x "${TMP}/bin/cap"

cat >"${TMP}/core/bootstrap.sh" <<'EOF'
#!/usr/bin/env bash
:
EOF
cat >"${TMP}/bin/dsm" <<'EOF'
#!/usr/bin/env bash
printf 'DSM:'
printf ' %s' "$@"
printf '\n'
EOF
chmod +x "${TMP}/bin/dsm"
cat >"${TMP}/agents/linux/runtime/local_cli.py" <<'EOF'
#!/usr/bin/env python3
import sys
print("LOCAL:" + " ".join(sys.argv[1:]))
EOF
cat >"${TMP}/agents/linux/runtime/cap_dispatch.py" <<'EOF'
#!/usr/bin/env python3
import sys
print("LOCAL:" + " ".join(sys.argv[1:]))
EOF
cat >"${TMP}/database/agent_deploy_cli.py" <<'EOF'
#!/usr/bin/env python3
import sys
print("DEPLOY:" + " ".join(sys.argv[1:]))
EOF

fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# Controller may administer Agents, but may not use local Agent operations.
out="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" agent deploy node.example --ssh-user admin)"
[[ "${out}" == "DEPLOY:node.example --ssh-user admin" ]] || fail "controller deploy route failed"
if DSM_NODE_ROLE=controller "${TMP}/bin/cap" agent status >/dev/null 2>"${TMP}/err"; then
    fail "controller was allowed to run local Agent status"
fi
grep -Fq "requer role agent ou hybrid" "${TMP}/err" || fail "controller denial lacks role message"
if DSM_NODE_ROLE=controller "${TMP}/bin/cap" instance restart instance-one >/dev/null 2>"${TMP}/err"; then
    fail "controller was allowed to run local instance lifecycle"
fi
grep -Fq "requer role agent ou hybrid" "${TMP}/err" || fail "controller instance denial lacks role message"

# Agent may use local surfaces, including structured instance lifecycle, but not Controller administration.
out="$(DSM_NODE_ROLE=agent "${TMP}/bin/cap" agent status --json)"
[[ "${out}" == "LOCAL:status --json" ]] || fail "agent local status route failed"
out="$(DSM_NODE_ROLE=agent "${TMP}/bin/cap" instance restart instance-one --json)"
[[ "${out}" == "LOCAL:instance restart instance-one --json" ]] || fail "agent instance lifecycle route failed"
if DSM_NODE_ROLE=agent "${TMP}/bin/cap" agent deploy node.example --ssh-user admin >/dev/null 2>"${TMP}/err"; then
    fail "agent was allowed to deploy another Agent"
fi
grep -Fq "requer role controller ou hybrid" "${TMP}/err" || fail "agent denial lacks role message"

# The ports collision is resolved by signature.
out="$(DSM_NODE_ROLE=agent "${TMP}/bin/cap" agent ports show --json)"
[[ "${out}" == "LOCAL:ports show --json" ]] || fail "local ports show did not route to local CLI"
out="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" agent ports show agent-remote)"
[[ "${out}" == "DSM: agent ports show agent-remote" ]] || fail "administrative ports show did not route to Controller surface"

# Hybrid gets both surfaces.
out="$(DSM_NODE_ROLE=hybrid "${TMP}/bin/cap" agent status)"
[[ "${out}" == "LOCAL:status" ]] || fail "hybrid local Agent route failed"
out="$(DSM_NODE_ROLE=hybrid "${TMP}/bin/cap" instance start instance-one)"
[[ "${out}" == "LOCAL:instance start instance-one" ]] || fail "hybrid local instance lifecycle route failed"
out="$(DSM_NODE_ROLE=hybrid "${TMP}/bin/cap" agent ports set agent-remote 24000 24999 --protocol udp)"
[[ "${out}" == "DSM: agent ports set agent-remote 24000 24999 --protocol udp" ]] || fail "hybrid administrative route failed"

# Unknown role fails closed before dispatch.
if env -u DSM_NODE_ROLE -u CAPIVARA_NODE_ROLE CAPIVARA_AGENT_CONFIG="${TMP}/missing.json" "${TMP}/bin/cap" update check >/dev/null 2>"${TMP}/err"; then
    fail "unknown role was allowed to dispatch"
fi
grep -Fq 'Role local detectada: unknown.' "${TMP}/err" || fail "unknown denial not explicit"

printf 'OK: CLI role enforcement contracts\n'
