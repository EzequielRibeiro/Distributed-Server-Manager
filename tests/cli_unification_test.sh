#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

mkdir -p "${TMP}/bin" "${TMP}/core"
cp "${ROOT}/bin/cap" "${TMP}/bin/cap"
cp "${ROOT}/core/role_context.py" "${TMP}/core/role_context.py"
chmod +x "${TMP}/bin/cap"

cat >"${TMP}/core/bootstrap.sh" <<'EOF'
#!/usr/bin/env bash
:
EOF

# Mock the internal compatibility implementation, not the deprecated public
# `dsm` wrapper. Public callers should use `cap`.
cat >"${TMP}/bin/dsm-compat" <<'EOF'
#!/usr/bin/env bash
printf 'DSM:'
printf ' %s' "$@"
printf '\n'
EOF
chmod +x "${TMP}/bin/dsm-compat"

fail(){
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

out="$(DSM_NODE_ROLE=hybrid "${TMP}/bin/cap" backup create)"
[[ "${out}" == "DSM: backup create" ]] || fail "cap backup did not delegate to internal compatibility layer"

out="$(DSM_NODE_ROLE=hybrid "${TMP}/bin/cap" server status dayz instance-01)"
[[ "${out}" == "DSM: server status dayz instance-01" ]] || fail "cap server did not preserve arguments"

out="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" agent ports show agent-node02)"
[[ "${out}" == "DSM: agent ports show agent-node02" ]] || fail "controller agent ports did not delegate correctly"

help="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" --help 2>&1)"
grep -Fq 'cap agent deploy HOST --ssh-user USER' <<<"${help}" || fail "controller help lost native agent deploy"
! grep -Fq 'cap agent game-data list' <<<"${help}" || fail "controller help leaked Agent-local commands"

help_all="$(DSM_NODE_ROLE=controller "${TMP}/bin/cap" help --all 2>&1)"
grep -Fq 'cap agent game-data list' <<<"${help_all}" || fail "help --all lacks Agent-local commands"
grep -Fq '`cap` é a única CLI pública' <<<"${help_all}" || fail "help does not identify cap as the single public CLI"

after="$(cat "${ROOT}/bin/cap")"
grep -Fq 'require_role "cap agent deploy" controller hybrid' <<<"${after}" || fail "agent deploy lacks role enforcement"
grep -Fq 'ROLE_RESOLVER=' <<<"${after}" || fail "role resolver is not wired into cap"
grep -Fq 'bin/dsm-compat' <<<"${after}" || fail "cap still routes through public dsm"

printf 'OK: cap CLI unification routing contracts\n'
