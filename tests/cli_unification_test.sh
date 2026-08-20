#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

mkdir -p "${TMP}/bin" "${TMP}/core"
cp "${ROOT}/bin/cap" "${TMP}/bin/cap"
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

fail(){
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

out="$("${TMP}/bin/cap" backup create)"
[[ "${out}" == "DSM: backup create" ]] || fail "cap backup did not delegate to dsm"

out="$("${TMP}/bin/cap" server status dayz instance-01)"
[[ "${out}" == "DSM: server status dayz instance-01" ]] || fail "cap server did not preserve arguments"

out="$("${TMP}/bin/cap" agent ports show agent-node02)"
[[ "${out}" == "DSM: agent ports show agent-node02" ]] || fail "cap agent ports did not delegate correctly"

help="$({ "${TMP}/bin/cap" --help; } 2>&1)"
grep -Fq 'cap agent deploy HOST --ssh-user USER' <<<"${help}" || fail "help lost native agent deploy"
grep -Fq 'cap backup ...' <<<"${help}" || fail "help does not expose delegated commands"
grep -Fq '`cap` é a CLI oficial em consolidação' <<<"${help}" || fail "help does not state unification policy"

cap_source="$(cat "${ROOT}/bin/cap")"
grep -Fq 'exec python3 "${DSM_ROOT}/database/agent_deploy_cli.py"' <<<"${cap_source}" || fail "agent deploy is no longer native"
grep -Fq 'legacy_exec agent "$@"' <<<"${cap_source}" || fail "agent ports compatibility routing missing"

printf 'OK: cap CLI unification routing contracts\n'
