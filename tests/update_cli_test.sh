#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAP_CLI="${ROOT}/bin/cap"

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

FAKE_ROOT="${TMP_DIR}/dsm"

mkdir -p \
    "${FAKE_ROOT}/bin" \
    "${FAKE_ROOT}/core" \
    "${FAKE_ROOT}/update-manager"

cp "${CAP_CLI}" "${FAKE_ROOT}/bin/cap"
chmod +x "${FAKE_ROOT}/bin/cap"

cat >"${FAKE_ROOT}/core/bootstrap.sh" <<'EOF'
#!/usr/bin/env bash
export DSM_BOOTSTRAP_LOADED=1
export DSM_DATABASE_DRIVER="sqlite"
export DSM_DATABASE=""
export DSM_DATABASE_HOST=""
export DSM_DATABASE_PORT=""
export DSM_DATABASE_NAME=""
export DSM_DATABASE_USER=""
export DSM_DATABASE_PASSWORD_FILE=""
export DSM_DATABASE_TLS=""
EOF

cat >"${FAKE_ROOT}/core/role_context.py" <<'EOF'
#!/usr/bin/env python3
print("controller")
EOF

cat >"${FAKE_ROOT}/update-manager/update-manager.sh" <<'EOF'
#!/usr/bin/env bash
dsm_update_check(){ echo "STUB_UPDATE_CHECK"; return 0; }
dsm_update_run(){ echo "STUB_UPDATE_RUN"; return 0; }
dsm_update_history(){ echo "STUB_UPDATE_HISTORY"; return 0; }
EOF

cat >"${FAKE_ROOT}/update-manager/preflight-latest.sh" <<'EOF'
#!/usr/bin/env bash
echo "STUB_UPDATE_PREFLIGHT"
EOF

chmod +x \
    "${FAKE_ROOT}/update-manager/update-manager.sh" \
    "${FAKE_ROOT}/update-manager/preflight-latest.sh"

OUTPUT="$("${FAKE_ROOT}/bin/cap" update check)"
[[ "$?" -eq 0 ]] || fail "cap update check falhou"
[[ "${OUTPUT}" == "STUB_UPDATE_CHECK" ]] || fail "cap update check nao chegou ao dispatcher esperado"

OUTPUT="$("${FAKE_ROOT}/bin/cap" update preflight)"
[[ "$?" -eq 0 ]] || fail "cap update preflight falhou"
[[ "${OUTPUT}" == "STUB_UPDATE_PREFLIGHT" ]] || fail "cap update preflight nao chegou ao dispatcher esperado"

OUTPUT="$("${FAKE_ROOT}/bin/cap" update run)"
[[ "$?" -eq 0 ]] || fail "cap update run falhou"
[[ "${OUTPUT}" == "STUB_UPDATE_RUN" ]] || fail "cap update run nao chegou ao dispatcher esperado"

OUTPUT="$("${FAKE_ROOT}/bin/cap" update history)"
[[ "$?" -eq 0 ]] || fail "cap update history falhou"
[[ "${OUTPUT}" == "STUB_UPDATE_HISTORY" ]] || fail "cap update history nao chegou ao dispatcher esperado"

set +e
OUTPUT="$("${FAKE_ROOT}/bin/cap" update invalid 2>&1)"
STATUS=$?
set -e
[[ "${STATUS}" -eq 2 ]] || fail "acao invalida deveria retornar 2; retornou ${STATUS}"
for expected in 'cap update check' 'cap update preflight' 'cap update run' 'cap update history'; do
    grep -q "${expected}" <<<"${OUTPUT}" || fail "usage nao contem ${expected}"
done

set +e
"${FAKE_ROOT}/bin/cap" update >/dev/null 2>&1
STATUS=$?
set -e
[[ "${STATUS}" -eq 2 ]] || fail "update sem acao deveria retornar 2; retornou ${STATUS}"

[[ ! -e "${FAKE_ROOT}/bin/dsm" ]] || fail "alias dsm foi reintroduzido no fixture"
[[ ! -e "${FAKE_ROOT}/bin/dsm-compat" ]] || fail "dispatcher dsm-compat foi reintroduzido no fixture"
[[ ! -e "${FAKE_ROOT}/update.sh" ]] || fail "ambiente de teste contem update.sh inesperadamente"

bash "${ROOT}/tests/update_preflight_test.sh"

echo "Update CLI tests passed."
