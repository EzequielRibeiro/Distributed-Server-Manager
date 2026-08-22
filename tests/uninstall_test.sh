#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/capivara-uninstall-test.XXXXXX")"
trap 'rm -rf -- "${TMP_DIR}"' EXIT
fail(){ echo "FAIL: $*" >&2; exit 1; }

export CAPIVARA_UNINSTALL_TESTING=1
export INSTALL_DIR="${TMP_DIR}/opt/dsm"
export BACKUP_DIR="${TMP_DIR}/opt/dsm-backup"
export SYSTEMD_DIR="${TMP_DIR}/systemd"
export DSM_LINK="${TMP_DIR}/bin/dsm"
export CAP_LINK="${TMP_DIR}/bin/cap"
export CONFIG_FILE="${INSTALL_DIR}/config/dsm.conf"
# shellcheck source=../uninstall.sh
source "${ROOT}/uninstall.sh"

mkdir -p "${INSTALL_DIR}/config" "${SYSTEMD_DIR}" "$(dirname "${DSM_LINK}")"
printf '%s\n' 'DSM_USER="capivara"' 'DSM_GROUP="capivara"' >"${CONFIG_FILE}"
: >"${SYSTEMD_DIR}/dsm-monitor.service"
: >"${SYSTEMD_DIR}/dsm-notification-engine.timer"
: >"${SYSTEMD_DIR}/unrelated.service"
printf 'ExecStart=%s/bin/cap daemon\n' "${INSTALL_DIR}" >"${SYSTEMD_DIR}/capivara-controller.service"
printf 'ExecStart=/srv/game/server\n' >"${SYSTEMD_DIR}/capivara-instance-game.service"
: >"${DSM_LINK}"
: >"${CAP_LINK}"

systemctl()
{
    case "$1" in
        list-unit-files) printf '%s\n' 'dsm-monitor.service enabled' 'dsm-notification-engine.timer enabled' ;;
        cat) command cat "${SYSTEMD_DIR}/$2" ;;
        *) printf '%s\n' "$*" >>"${TMP_DIR}/systemctl.log" ;;
    esac
}

load_config >/dev/null
[[ "${DSM_USER}:${DSM_GROUP}" == capivara:capivara ]] || fail "service identity was not read"
mapfile -t units < <(discover_managed_units)
[[ " ${units[*]} " == *" dsm-monitor.service "* ]] || fail "service not discovered"
[[ " ${units[*]} " == *" dsm-notification-engine.timer "* ]] || fail "timer not discovered"
[[ " ${units[*]} " == *" capivara-controller.service "* ]] || fail "capivara unit not discovered"
[[ " ${units[*]} " != *" capivara-instance-game.service "* ]] || fail "external game unit selected"
[[ " ${units[*]} " != *" unrelated.service "* ]] || fail "unrelated unit selected"

remove_systemd_units >/dev/null
[[ ! -e "${SYSTEMD_DIR}/dsm-monitor.service" ]] || fail "service not removed"
[[ ! -e "${SYSTEMD_DIR}/dsm-notification-engine.timer" ]] || fail "timer not removed"
[[ ! -e "${SYSTEMD_DIR}/capivara-controller.service" ]] || fail "capivara unit not removed"
[[ -e "${SYSTEMD_DIR}/unrelated.service" ]] || fail "unrelated unit removed"
[[ -e "${SYSTEMD_DIR}/capivara-instance-game.service" ]] || fail "external game unit removed"
grep -Fq 'disable --now dsm-monitor.service' "${TMP_DIR}/systemctl.log" || fail "service not disabled"
grep -Fq 'daemon-reload' "${TMP_DIR}/systemctl.log" || fail "daemon-reload not called"
grep -Fq 'reset-failed' "${TMP_DIR}/systemctl.log" || fail "reset-failed not called"

systemctl(){ [[ "$1" == list-unit-files ]] && return 0; return 0; }
remove_commands >/dev/null
remove_installation >/dev/null
[[ ! -e "${DSM_LINK}" && ! -L "${DSM_LINK}" ]] || fail "dsm link remains"
[[ ! -e "${CAP_LINK}" && ! -L "${CAP_LINK}" ]] || fail "cap link remains"
[[ ! -e "${INSTALL_DIR}" ]] || fail "install directory remains"
validate_uninstall >/dev/null

INSTALL_DIR=/
if (validate_paths >/dev/null 2>&1); then fail "path protection accepted root"; fi
echo "uninstall tests: OK"
