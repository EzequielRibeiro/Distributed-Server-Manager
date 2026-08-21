#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DSM_CLI="${ROOT}/bin/dsm"
CAP_CLI="${ROOT}/bin/cap"
DSM_COMPAT="${ROOT}/bin/dsm-compat"

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

cp "${DSM_CLI}" "${FAKE_ROOT}/bin/dsm"
cp "${CAP_CLI}" "${FAKE_ROOT}/bin/cap"
cp "${DSM_COMPAT}" "${FAKE_ROOT}/bin/dsm-compat"
chmod +x "${FAKE_ROOT}/bin/dsm" "${FAKE_ROOT}/bin/cap" "${FAKE_ROOT}/bin/dsm-compat"

# -------------------------------------------------------------
# Bootstrap minimo para o teste do dispatcher CLI
# -------------------------------------------------------------

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

# A CLI publica `cap` e role-aware. O fixture simula um Controller para
# que `dsm -> cap -> dsm-compat` valide o mesmo caminho usado em producao.
cat >"${FAKE_ROOT}/core/role_context.py" <<'EOF'
#!/usr/bin/env python3
print("controller")
EOF

# -------------------------------------------------------------
# Update Manager stub
#
# Impede acesso a rede, releases e update.sh real.
# -------------------------------------------------------------

cat >"${FAKE_ROOT}/update-manager/update-manager.sh" <<'EOF'
#!/usr/bin/env bash

dsm_update_check()
{
    echo "STUB_UPDATE_CHECK"
    return 0
}

dsm_update_run()
{
    echo "STUB_UPDATE_RUN"
    return 0
}

dsm_update_history()
{
    echo "STUB_UPDATE_HISTORY"
    return 0
}
EOF

chmod +x "${FAKE_ROOT}/update-manager/update-manager.sh"

# -------------------------------------------------------------
# check
# -------------------------------------------------------------

OUTPUT="$(DSM_QUIET_DEPRECATION=1 "${FAKE_ROOT}/bin/dsm" update check)"
STATUS=$?

[[ "${STATUS}" -eq 0 ]] \
    || fail "dsm update check retornou ${STATUS}"

[[ "${OUTPUT}" == "STUB_UPDATE_CHECK" ]] \
    || fail "dsm update check nao chegou ao dispatcher esperado"

# -------------------------------------------------------------
# run
# -------------------------------------------------------------

OUTPUT="$(DSM_QUIET_DEPRECATION=1 "${FAKE_ROOT}/bin/dsm" update run)"
STATUS=$?

[[ "${STATUS}" -eq 0 ]] \
    || fail "dsm update run retornou ${STATUS}"

[[ "${OUTPUT}" == "STUB_UPDATE_RUN" ]] \
    || fail "dsm update run nao chegou ao dispatcher esperado"

# -------------------------------------------------------------
# history
# -------------------------------------------------------------

OUTPUT="$(DSM_QUIET_DEPRECATION=1 "${FAKE_ROOT}/bin/dsm" update history)"
STATUS=$?

[[ "${STATUS}" -eq 0 ]] \
    || fail "dsm update history retornou ${STATUS}"

[[ "${OUTPUT}" == "STUB_UPDATE_HISTORY" ]] \
    || fail "dsm update history nao chegou ao dispatcher esperado"

# -------------------------------------------------------------
# Acao invalida
# -------------------------------------------------------------

set +e
OUTPUT="$(DSM_QUIET_DEPRECATION=1 "${FAKE_ROOT}/bin/dsm" update invalid 2>&1)"
STATUS=$?
set -e

[[ "${STATUS}" -eq 2 ]] \
    || fail "acao invalida deveria retornar 2; retornou ${STATUS}"

grep -q 'dsm update check' <<<"${OUTPUT}" \
    || fail "usage nao contem update check"

grep -q 'dsm update run' <<<"${OUTPUT}" \
    || fail "usage nao contem update run"

grep -q 'dsm update history' <<<"${OUTPUT}" \
    || fail "usage nao contem update history"

# -------------------------------------------------------------
# update sem acao
# -------------------------------------------------------------

set +e
OUTPUT="$(DSM_QUIET_DEPRECATION=1 "${FAKE_ROOT}/bin/dsm" update 2>&1)"
STATUS=$?
set -e

[[ "${STATUS}" -eq 2 ]] \
    || fail "update sem acao deveria retornar 2; retornou ${STATUS}"

# -------------------------------------------------------------
# Garantia de isolamento
# -------------------------------------------------------------

[[ ! -e "${FAKE_ROOT}/update.sh" ]] \
    || fail "ambiente de teste contem update.sh inesperadamente"

echo "Update CLI tests passed."
