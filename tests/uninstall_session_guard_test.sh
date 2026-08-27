#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
INSTALL_DIR="${TMP}/dsm"
mkdir -p "${INSTALL_DIR}"

cleanup()
{
    [[ -n "${CWD_PID:-}" ]] && kill "${CWD_PID}" 2>/dev/null || true
    [[ -n "${MANAGED_PID:-}" ]] && kill "${MANAGED_PID}" 2>/dev/null || true
    rm -rf -- "${TMP}"
}
trap cleanup EXIT

export CAPIVARA_UNINSTALL_TESTING=1
export INSTALL_DIR
export BACKUP_DIR="${TMP}/backup"
export DSM_LINK="${TMP}/bin/dsm"
export CAP_LINK="${TMP}/bin/cap"
export SYSTEMD_DIR="${TMP}/systemd"
export CONFIG_FILE="${INSTALL_DIR}/config/dsm.conf"

# shellcheck source=../uninstall.sh
source "${ROOT}/uninstall.sh"

process_is_uninstall_ancestor "$$" || {
    echo "FAIL: uninstall process must protect itself" >&2
    exit 1
}

# A process whose only relation to INSTALL_DIR is cwd must not be selected.
(
    cd "${INSTALL_DIR}"
    exec sleep 30
) &
CWD_PID=$!
sleep 0.1
if process_references_install "${CWD_PID}"
then
    echo "FAIL: cwd-only process was classified as Capivara-managed" >&2
    exit 1
fi

cat > "${INSTALL_DIR}/managed-worker.sh" <<'EOF'
#!/usr/bin/env bash
while :; do sleep 1; done
EOF
chmod +x "${INSTALL_DIR}/managed-worker.sh"
bash "${INSTALL_DIR}/managed-worker.sh" &
MANAGED_PID=$!
sleep 0.1
if ! process_references_install "${MANAGED_PID}"
then
    echo "FAIL: managed process referencing INSTALL_DIR was not detected" >&2
    exit 1
fi

FOUND="$(find_install_processes | tr '\n' ' ')"
[[ " ${FOUND} " != *" ${CWD_PID} "* ]] || {
    echo "FAIL: cwd-only process leaked into residual-process list" >&2
    exit 1
}
[[ " ${FOUND} " == *" ${MANAGED_PID} "* ]] || {
    echo "FAIL: managed process missing from residual-process list" >&2
    exit 1
}

echo "PASS: uninstall preserves invoking/SSH-style sessions while detecting managed processes"
