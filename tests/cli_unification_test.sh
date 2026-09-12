#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

mkdir -p \
    "${TMP}/bin" \
    "${TMP}/core" \
    "${TMP}/backup" \
    "${TMP}/server" \
    "${TMP}/database"
cp "${ROOT}/bin/cap" "${TMP}/bin/cap"
cp "${ROOT}/core/role_context.py" "${TMP}/core/role_context.py"
chmod +x "${TMP}/bin/cap"

cat >"${TMP}/core/bootstrap.sh" <<'EOF'
#!/usr/bin/env bash
:
EOF

cat >"${TMP}/backup/create.sh" <<'EOF'
#!/usr/bin/env bash
backup_create(){
    printf 'BACKUP:'
    printf ' %s' "$@"
    printf '\n'
}
EOF

cat >"${TMP}/server/status.sh" <<'EOF'
#!/usr/bin/env bash
server_status(){
    printf 'SERVER:%s:%s\n' "${GAME_ID:-}" "${DSM_INSTANCE_ID:-}"
}
EOF

cat >"${TMP}/database/agent_ports_cli.py" <<'EOF'
#!/usr/bin/env python3
import sys
print("PORTS:" + " ".join(sys.argv[1:]))
EOF

fail(){
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

out="$(DSM_NODE_ROLE=hybrid "${TMP}/bin/cap" backup create snapshot-a)"
[[ "${out}" == "BACKUP: snapshot-a" ]] || fail "cap backup did not route directly to backup implementation: ${out}"

out="$(DSM_NODE_ROLE=hybrid "${TMP}/bin/cap" server status dayz instance-01)"
[[ "${out}" == "SERVER:dayz:instance-01" ]] || fail "cap server did not route directly while preserving game/instance: ${out}"

out="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" agent ports show agent-node02)"
[[ "${out}" == "PORTS:show agent-node02" ]] || fail "controller agent ports did not route directly: ${out}"

help="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" --help 2>&1)"
grep -Fq 'cap agent deploy HOST --ssh-user USER' <<<"${help}" || fail "controller help lost native agent deploy"
grep -Fq 'cap user add <usuário> <admin|operator|controller|customer> [scope]' <<<"${help}" \
    || fail "controller help does not document user creation"
grep -Fq 'cap user passwd <usuário>' <<<"${help}" \
    || fail "controller help does not document password management"
! grep -Fq 'cap agent game-data list' <<<"${help}" || fail "controller help leaked Agent-local commands"

help_all="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" help --all 2>&1)"
grep -Fq 'cap agent game-data list' <<<"${help_all}" || fail "help --all lacks Agent-local commands"
grep -Fq '`cap` é a única CLI do Capivara DSM.' <<<"${help_all}" || fail "help does not identify cap as the single CLI"

after="$(cat "${ROOT}/bin/cap")"
grep -Fq 'require_role "cap agent deploy" controller hybrid' <<<"${after}" || fail "agent deploy lacks role enforcement"
grep -Fq 'ROLE_RESOLVER=' <<<"${after}" || fail "role resolver is not wired into cap"
grep -Fq 'server) require_role "cap server" agent hybrid; shift; server_command "$@"' <<<"${after}" || fail "server command is not routed directly"
grep -Fq 'backup) require_role "cap backup" agent hybrid; shift; backup_command "$@"' <<<"${after}" || fail "backup command is not routed directly"
! grep -Fq 'dsm-compat' <<<"${after}" || fail "retired dsm-compat routing remains in cap"
! grep -Fq 'LEGACY_DSM' <<<"${after}" || fail "retired LEGACY_DSM remains in cap"
! grep -Fq 'legacy_exec' <<<"${after}" || fail "retired legacy_exec remains in cap"

printf 'OK: cap direct routing contracts\n'
