#!/usr/bin/env bash
# Capivara DSM - Generic Runtime/Content Update Monitor
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_ROOT="${DSM_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
VERSION_ADAPTER_ROOT="${DSM_PROVIDER_VERSION_ADAPTER_ROOT:-${DSM_ROOT}/installer/provider_versions}"

# shellcheck source=/dev/null
source "${DSM_ROOT}/installer/provider_loader.sh"

update_error(){ echo "[DSM][UPDATE][ERROR] $*" >&2; }

update_validate_kind()
{
    case "${1:-}" in runtime|content) return 0 ;; esac
    update_error "Kind must be runtime or content."
    return 2
}

update_load_provider()
{
    local PROVIDER="${1:-}" ADAPTER
    unset -f provider_remote_version 2>/dev/null || true
    provider_require "${PROVIDER}" || return 1

    ADAPTER="${VERSION_ADAPTER_ROOT}/${PROVIDER}.sh"
    if [[ -f "${ADAPTER}" ]]; then
        # Version adapters extend provider contracts without game-specific logic.
        # shellcheck source=/dev/null
        source "${ADAPTER}"
    fi
}

update_probe()
{
    local KIND="${1:-}" PROVIDER="${2:-}" PACKAGE="${3:-}" INSTALL_PATH="${4:-}"
    local INSTALLED REMOTE STATUS

    update_validate_kind "${KIND}" || return $?
    [[ -n "${PROVIDER}" && -n "${PACKAGE}" && -n "${INSTALL_PATH}" ]] || {
        update_error "Provider, package and install path are required."
        return 2
    }

    # Provider bootstrap logs go to stderr so stdout remains a stable JSON contract.
    update_load_provider "${PROVIDER}" >&2 || return 1

    if ! declare -F provider_version >/dev/null 2>&1; then
        update_error "Provider ${PROVIDER} does not expose installed version."
        return 3
    fi
    if ! declare -F provider_remote_version >/dev/null 2>&1; then
        jq -n --arg kind "${KIND}" --arg provider "${PROVIDER}" --arg package "${PACKAGE}" \
          '{schema_version:1,kind:"UpdateProbe",target_kind:$kind,provider:$provider,package:$package,status:"unsupported",installed_version:null,remote_version:null,update_available:false}'
        return 4
    fi

    INSTALLED="$(provider_version "${PACKAGE}" "${INSTALL_PATH}" 2>/dev/null || true)"
    REMOTE="$(provider_remote_version "${PACKAGE}" "${INSTALL_PATH}" 2>/dev/null || true)"

    [[ -n "${INSTALLED}" ]] || INSTALLED="unknown"
    [[ -n "${REMOTE}" ]] || {
        update_error "Provider ${PROVIDER} could not resolve remote version for ${PACKAGE}."
        return 1
    }

    if [[ "${INSTALLED}" == "unknown" || "${INSTALLED}" == "0" ]]; then
        STATUS="not_installed"
    elif [[ "${INSTALLED}" == "${REMOTE}" ]]; then
        STATUS="current"
    else
        STATUS="update_available"
    fi

    jq -n \
      --arg kind "${KIND}" --arg provider "${PROVIDER}" --arg package "${PACKAGE}" \
      --arg installed "${INSTALLED}" --arg remote "${REMOTE}" --arg status "${STATUS}" \
      '{schema_version:1,kind:"UpdateProbe",target_kind:$kind,provider:$provider,package:$package,status:$status,installed_version:$installed,remote_version:$remote,update_available:($status=="update_available")}'
}

update_apply_runtime()
{
    local PROVIDER="${1:-}" GAME_ID="${2:-}" PACKAGE="${3:-}" INSTALL_PATH="${4:-}" EXECUTABLE="${5:-}" INSTALL_USER="${6:-anonymous}"
    # Atomic Engine owns staging, integrity validation, activation and rollback.
    # shellcheck source=/dev/null
    source "${DSM_ROOT}/installer/atomic_install.sh"
    atomic_install "${PROVIDER}" "${GAME_ID}" "${PACKAGE}" "${INSTALL_PATH}" "${EXECUTABLE}" "${INSTALL_USER}"
}

update_apply_content()
{
    local REQUEST="${1:-}" INSTANCE="${2:-}"
    [[ -f "${REQUEST}" ]] || { update_error "Content request not found: ${REQUEST}"; return 2; }
    [[ -n "${INSTANCE}" ]] || { update_error "Instance path is required."; return 2; }
    # Content Manager owns planning, staging, activation adapters and rollback.
    "${DSM_ROOT}/installer/content_manager.sh" install "${REQUEST}" "${INSTANCE}"
}

case "${1:-}" in
    probe)
        [[ $# -eq 5 ]] || { echo "Usage: update_monitor.sh probe <runtime|content> <provider> <package> <install_path>" >&2; exit 2; }
        update_probe "$2" "$3" "$4" "$5"
        ;;
    apply-runtime)
        [[ $# -ge 6 && $# -le 7 ]] || { echo "Usage: update_monitor.sh apply-runtime <provider> <game_id> <package> <install_path> <executable> [install_user]" >&2; exit 2; }
        update_apply_runtime "$2" "$3" "$4" "$5" "$6" "${7:-anonymous}"
        ;;
    apply-content)
        [[ $# -eq 3 ]] || { echo "Usage: update_monitor.sh apply-content <request.json> <instance_path>" >&2; exit 2; }
        update_apply_content "$2" "$3"
        ;;
    *)
        echo "Usage: update_monitor.sh {probe|apply-runtime|apply-content} ..." >&2
        exit 2
        ;;
esac
