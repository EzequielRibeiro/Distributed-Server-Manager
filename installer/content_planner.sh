#!/usr/bin/env bash
# Capivara DSM - Content dependency planner v2
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_ROOT="${DSM_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CONTENT_ROOT="${DSM_CATALOG_ROOT:-${DSM_ROOT}/catalog/v2}/content"
COMPATIBILITY="${DSM_ROOT}/installer/compatibility_resolver.sh"

declare -A PLANNER_VISITING=()
declare -A PLANNER_VISITED=()
declare -a PLANNER_ORDER=()

planner_error(){ echo "[DSM][CONTENT-PLAN][ERROR] $*" >&2; }

planner_definition()
{
    local ID="$1" FILE
    while IFS= read -r -d '' FILE; do
        if jq -e --arg id "${ID}" '.id == $id' "${FILE}" >/dev/null; then printf '%s\n' "${FILE}"; return 0; fi
    done < <(find "${CONTENT_ROOT}" -type f -name '*.json' -print0)
    return 1
}

planner_visit()
{
    local ID="$1" FILE DEP
    [[ "${PLANNER_VISITED[${ID}]:-0}" == 1 ]] && return 0
    if [[ "${PLANNER_VISITING[${ID}]:-0}" == 1 ]]; then planner_error "Dependency cycle detected at ${ID}."; return 1; fi
    FILE="$(planner_definition "${ID}")" || { planner_error "Content not found: ${ID}"; return 1; }
    PLANNER_VISITING[${ID}]=1
    while IFS= read -r DEP; do [[ -n "${DEP}" ]] || continue; planner_visit "${DEP}" || return 1; done < <(jq -r '.dependencies[]? | select(.required != false) | .id' "${FILE}" | tr -d '\r')
    PLANNER_VISITING[${ID}]=0
    PLANNER_VISITED[${ID}]=1
    PLANNER_ORDER+=("${ID}")
}

planner_plan()
{
    local REQUEST="$1" INSTANCE="$2" RESULT ID FILE OPERATIONS="[]" EXPANDED_REQUEST CONTENT_IDS
    [[ -f "${REQUEST}" ]] || { planner_error "Request not found: ${REQUEST}"; return 2; }
    PLANNER_VISITING=(); PLANNER_VISITED=(); PLANNER_ORDER=()
    while IFS= read -r ID; do planner_visit "${ID}" || return 1; done < <(jq -r '.content[]' "${REQUEST}" | tr -d '\r')

    EXPANDED_REQUEST="$(mktemp)"; CONTENT_IDS="$(mktemp)"
    trap 'rm -f -- "${EXPANDED_REQUEST}" "${CONTENT_IDS}"' RETURN
    printf '%s\n' "${PLANNER_ORDER[@]}" | jq -Rsc 'split("\n")|map(select(length>0))' >"${CONTENT_IDS}"
    jq --slurpfile content "${CONTENT_IDS}" '.content=$content[0]' "${REQUEST}" >"${EXPANDED_REQUEST}"
    RESULT="$("${COMPATIBILITY}" check "${EXPANDED_REQUEST}")" || return 1
    if [[ "$(jq -r '.compatible' <<<"${RESULT}" | tr -d '\r')" != true ]]; then jq . <<<"${RESULT}"; return 1; fi

    for ID in "${PLANNER_ORDER[@]}"; do
        FILE="$(planner_definition "${ID}")"
        OPERATIONS="$(jq -c --argjson ops "${OPERATIONS}" '
            . as $d | $ops + [{
                action:"install", content_id:$d.id, content_type:$d.content_type,
                version:$d.version,
                target:(
                    if (($d.installation.target // "")|length)>0 then $d.installation.target
                    elif $d.content_type == "plugin" then "plugins"
                    elif $d.content_type == "mod" then "mods"
                    elif $d.content_type == "modpack" then "."
                    elif $d.content_type == "datapack" then "world/datapacks"
                    else error("unsupported content type") end
                ),
                artifact:$d.artifact,
                activation:($d.activation // null)
            }]' "${FILE}")"
    done

    jq -n --arg instance "${INSTANCE}" --arg runtime "$(jq -r '.runtime.id' "${REQUEST}")" \
      --argjson operations "${OPERATIONS}" --argjson generated_at "$(date +%s)" '{
        schema_version:2, kind:"InstallationPlan", instance:$instance,
        runtime:$runtime, generated_at:$generated_at, operations:$operations
      }'
}

case "${1:-}" in
    plan) [[ $# -eq 3 ]] || exit 2; planner_plan "$2" "$3" ;;
    *) echo "Usage: content_planner.sh plan REQUEST.json INSTANCE_PATH" >&2; exit 2 ;;
esac
