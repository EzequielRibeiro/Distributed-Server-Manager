#!/usr/bin/env bash
# Capivara DSM - Generic content activation dispatcher
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_ROOT="${DSM_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
ADAPTER_ROOT="${DSM_CONTENT_ADAPTER_ROOT:-${DSM_ROOT}/installer/content_adapters}"

activation_error(){ echo "[DSM][CONTENT-ACTIVATION][ERROR] $*" >&2; }

activation_validate_adapter()
{
    local NAME="${1:-}"
    [[ "${NAME}" =~ ^[a-z0-9][a-z0-9_-]+$ ]] || {
        activation_error "Invalid adapter name: ${NAME}"
        return 2
    }
}

activation_render()
{
    local PLAN="${1:-}" INSTANCE="${2:-}" TMP ADAPTER FILE RESULT
    [[ -f "${PLAN}" ]] || { activation_error "Installation plan not found."; return 2; }
    [[ -n "${INSTANCE}" && "${INSTANCE}" == /* && "${INSTANCE}" != "/" ]] || {
        activation_error "Instance path must be absolute and non-root."
        return 2
    }

    TMP="$(mktemp -d)"
    # The dispatcher executes adapter functions in the same shell. A RETURN trap
    # would fire when an adapter returns and delete the accumulator too early.
    trap 'rm -rf -- "${TMP}"' EXIT
    printf '[]\n' >"${TMP}/operations.json"

    while IFS= read -r ADAPTER; do
        [[ -n "${ADAPTER}" ]] || continue
        activation_validate_adapter "${ADAPTER}" || return $?
        FILE="${ADAPTER_ROOT}/${ADAPTER}.sh"
        [[ -f "${FILE}" ]] || { activation_error "Activation adapter not found: ${ADAPTER}"; return 1; }

        unset -f content_adapter_render 2>/dev/null || true
        # shellcheck source=/dev/null
        source "${FILE}"
        declare -F content_adapter_render >/dev/null 2>&1 || {
            activation_error "Adapter ${ADAPTER} does not implement content_adapter_render()."
            return 1
        }

        RESULT="$(content_adapter_render "${PLAN}" "${INSTANCE}")" || return 1
        jq -e 'type=="array"' <<<"${RESULT}" >/dev/null || {
            activation_error "Adapter ${ADAPTER} returned an invalid activation payload."
            return 1
        }
        jq --argjson add "${RESULT}" '. + $add' "${TMP}/operations.json" >"${TMP}/next.json"
        mv -- "${TMP}/next.json" "${TMP}/operations.json"
    done < <(jq -r '[.operations[]? | .activation.adapter? // empty] | unique[]' "${PLAN}" | tr -d '\r')

    jq -n \
        --arg instance "${INSTANCE}" \
        --arg runtime "$(jq -r '.runtime // "unknown"' "${PLAN}")" \
        --slurpfile operations "${TMP}/operations.json" \
        '{schema_version:1,kind:"ContentActivation",instance:$instance,runtime:$runtime,operations:$operations[0]}'
}

case "${1:-}" in
    render) [[ $# -eq 3 ]] || exit 2; activation_render "$2" "$3" ;;
    *) echo "Usage: content_activation.sh render PLAN.json INSTANCE_PATH" >&2; exit 2 ;;
esac
