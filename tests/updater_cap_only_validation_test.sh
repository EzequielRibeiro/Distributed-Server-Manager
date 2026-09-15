#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPDATE="${ROOT}/update.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

INSTALL="${TMP_DIR}/opt/dsm"
mkdir -p "${INSTALL}/bin" "${INSTALL}/core" "${INSTALL}/config"
printf '#!/usr/bin/env bash\nexit 0\n' >"${INSTALL}/bin/cap"
printf '# bootstrap\n' >"${INSTALL}/core/bootstrap.sh"
printf 'DSM_VERSION="test"\n' >"${INSTALL}/config/dsm.conf"
chmod +x "${INSTALL}/bin/cap"

# Capivara is cap-only: bin/dsm must not be required by final validation.
(
    source "${UPDATE}"
    INSTALL_DIR="${INSTALL}"
    validate_final_installation >/dev/null
) || fail "cap-only installation was rejected because bin/dsm is absent"

# The canonical public CLI remains mandatory.
rm -f -- "${INSTALL}/bin/cap"
if (
    source "${UPDATE}"
    INSTALL_DIR="${INSTALL}"
    validate_final_installation >/dev/null 2>&1
); then
    fail "final validation accepted an installation without bin/cap"
fi

echo "OK: updater final validation is cap-only"
