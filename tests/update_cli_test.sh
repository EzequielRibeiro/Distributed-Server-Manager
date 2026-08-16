#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${ROOT}/bin/dsm"

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

cp "${CLI}" "${FAKE_ROOT}/bin/dsm"
chmod +x "${FAKE_ROOT}/bin/dsm"

# -------------------------------------------------------------
# Bootstrap minimo para o teste do dispatcher CLI
# -------------------------------------------------------------

cat >"${FAKE_ROOT}/core/bootstrap.sh" <<'EOF'
#!/usr/bin/env bash

export DSM_BOOTSTRAP_LOADED=1
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

OUTPUT="$("${FAKE_ROOT}/bin/dsm" update check)"
STATUS=$?

[[ "${STATUS}" -eq 0 ]] \
    || fail "dsm update check retornou ${STATUS}"

[[ "${OUTPUT}" == "STUB_UPDATE_CHECK" ]] \
    || fail "dsm update check nao chegou ao dispatcher esperado"

# -------------------------------------------------------------
# run
# -------------------------------------------------------------

OUTPUT="$("${FAKE_ROOT}/bin/dsm" update run)"
STATUS=$?

[[ "${STATUS}" -eq 0 ]] \
    || fail "dsm update run retornou ${STATUS}"

[[ "${OUTPUT}" == "STUB_UPDATE_RUN" ]] \
    || fail "dsm update run nao chegou ao dispatcher esperado"

# -------------------------------------------------------------
# history
# -------------------------------------------------------------

OUTPUT="$("${FAKE_ROOT}/bin/dsm" update history)"
STATUS=$?

[[ "${STATUS}" -eq 0 ]] \
    || fail "dsm update history retornou ${STATUS}"

[[ "${OUTPUT}" == "STUB_UPDATE_HISTORY" ]] \
    || fail "dsm update history nao chegou ao dispatcher esperado"

# -------------------------------------------------------------
# Acao invalida
# -------------------------------------------------------------

set +e
OUTPUT="$("${FAKE_ROOT}/bin/dsm" update invalid 2>&1)"
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
OUTPUT="$("${FAKE_ROOT}/bin/dsm" update 2>&1)"
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
