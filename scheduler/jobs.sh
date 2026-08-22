#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
SCHEDULER_DIR="${DSM_ROOT}/scheduler"
TASKS_DIR="${SCHEDULER_DIR}/tasks"
JOBS_DB="${SCHEDULER_DIR}/jobs.db"
LOCK_FILE="${DSM_ROOT}/cache/scheduler_jobs.lock"

jobs_lock()
{
    mkdir -p "$(dirname "${LOCK_FILE}")"
    if declare -f lock_acquire >/dev/null; then lock_acquire "${LOCK_FILE}"; return $?; fi
    mkdir "${LOCK_FILE}.d" 2>/dev/null || { echo "Erro: jobs.db bloqueado" >&2; return 1; }
}

jobs_unlock()
{
    if declare -f lock_release >/dev/null; then lock_release "${LOCK_FILE}"; else rm -rf "${LOCK_FILE}.d"; fi
}

jobs_init()
{
    command -v jq >/dev/null 2>&1 || { echo "Erro: jq não instalado" >&2; return 1; }
    mkdir -p "${SCHEDULER_DIR}"
    [[ -f "${JOBS_DB}" ]] || printf '%s\n' '{"jobs":[]}' >"${JOBS_DB}"
    jq -e '.jobs | type == "array"' "${JOBS_DB}" >/dev/null 2>&1 || { echo "Erro: jobs.db inválido" >&2; return 1; }
}

jobs_validate_schedule()
{
    local schedule="${1:-}"
    case "${schedule}" in
        @daily|@hourly|@weekly|@monthly) return 0 ;;
        @every:*) [[ "${schedule#@every:}" =~ ^[1-9][0-9]*$ ]] ;;
        *) [[ "${schedule}" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] ;;
    esac
}

jobs_exists()
{
    local name="$1"
    jobs_init >/dev/null || return 1
    jq -e --arg name "${name}" '.jobs[] | select(.name==$name)' "${JOBS_DB}" >/dev/null
}

jobs_list()
{
    jobs_init || return 1
    jq -r '.jobs[] | [.name,.schedule,.command,(.enabled|tostring),(.last_run_at // ""),(.last_status // "never")] | @tsv' "${JOBS_DB}" | tr '\t' '|'
}

jobs_list_json()
{
    jobs_init || return 1
    jq '{jobs:.jobs}' "${JOBS_DB}"
}

jobs_show()
{
    local name="$1"
    jobs_init || return 1
    jq --arg name "${name}" '.jobs[] | select(.name==$name)' "${JOBS_DB}"
}

jobs_add()
{
    local name="$1" schedule="$2" command="$3" enabled="${4:-1}" file="${5:-}"
    jobs_init || return 1
    jobs_validate_schedule "${schedule}" || { echo "Erro: schedule inválido: ${schedule}" >&2; return 2; }
    [[ "${enabled}" =~ ^[01]$ ]] || { echo "Erro: enabled deve ser 0 ou 1" >&2; return 2; }
    [[ -n "${name}" && -n "${command}" ]] || { echo "Erro: nome e comando são obrigatórios" >&2; return 2; }
    jobs_lock || return 1
    if jobs_exists "${name}"; then jobs_unlock; echo "Erro: job já existe: ${name}" >&2; return 2; fi
    local tmp; tmp="$(mktemp)"
    jq --arg name "${name}" --arg schedule "${schedule}" --arg command "${command}" --arg file "${file}" --argjson enabled "${enabled}" '
      .jobs += [{name:$name,schedule:$schedule,command:$command,enabled:$enabled,file:$file,created_at:(now|todate),updated_at:(now|todate),last_run_at:null,last_status:"never"}]' "${JOBS_DB}" >"${tmp}"
    mv "${tmp}" "${JOBS_DB}"
    jobs_unlock
}

jobs_update()
{
    local name="$1" field="$2" value="$3"
    jobs_init || return 1
    jobs_exists "${name}" || { echo "Erro: job inexistente: ${name}" >&2; return 2; }
    case "${field}" in
        schedule) jobs_validate_schedule "${value}" || { echo "Erro: schedule inválido" >&2; return 2; } ;;
        enabled) [[ "${value}" =~ ^[01]$ ]] || { echo "Erro: enabled inválido" >&2; return 2; } ;;
        command|file) ;;
        *) echo "Erro: campo inválido: ${field}" >&2; return 2 ;;
    esac
    jobs_lock || return 1
    local tmp; tmp="$(mktemp)"
    if [[ "${field}" == "enabled" ]]; then
        jq --arg name "${name}" --argjson value "${value}" '.jobs |= map(if .name==$name then .enabled=$value | .updated_at=(now|todate) else . end)' "${JOBS_DB}" >"${tmp}"
    else
        jq --arg name "${name}" --arg field "${field}" --arg value "${value}" '.jobs |= map(if .name==$name then .[$field]=$value | .updated_at=(now|todate) else . end)' "${JOBS_DB}" >"${tmp}"
    fi
    mv "${tmp}" "${JOBS_DB}"
    jobs_unlock
}

jobs_mark_run()
{
    local name="$1" status="$2"
    jobs_init || return 1
    jobs_lock || return 1
    local tmp; tmp="$(mktemp)"
    jq --arg name "${name}" --arg status "${status}" '.jobs |= map(if .name==$name then .last_run_at=(now|todate) | .last_status=$status | .updated_at=(now|todate) else . end)' "${JOBS_DB}" >"${tmp}"
    mv "${tmp}" "${JOBS_DB}"
    jobs_unlock
}

jobs_remove()
{
    local name="$1"
    jobs_init || return 1
    jobs_exists "${name}" || { echo "Erro: job não encontrado: ${name}" >&2; return 2; }
    jobs_lock || return 1
    local tmp; tmp="$(mktemp)"
    jq --arg name "${name}" '.jobs |= map(select(.name!=$name))' "${JOBS_DB}" >"${tmp}"
    mv "${tmp}" "${JOBS_DB}"
    jobs_unlock
}

jobs_enable(){ jobs_update "$1" enabled 1; }
jobs_disable(){ jobs_update "$1" enabled 0; }

jobs_import_tasks()
{
    jobs_init || return 1
    [[ -d "${TASKS_DIR}" ]] || return 0
    local task
    for task in "${TASKS_DIR}"/*.task; do
        [[ -f "${task}" ]] || continue
        unset NAME SCHEDULE COMMAND ENABLED
        # shellcheck source=/dev/null
        source "${task}"
        [[ -n "${NAME:-}" ]] || continue
        jobs_exists "${NAME}" || jobs_add "${NAME}" "${SCHEDULE}" "${COMMAND}" "${ENABLED:-1}" "${task}"
    done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-}" in
        list) jobs_list ;;
        list-json) jobs_list_json ;;
        show) jobs_show "${2:?job obrigatório}" ;;
        import) jobs_import_tasks ;;
        add) jobs_add "${2:?nome}" "${3:?schedule}" "${4:?comando}" "${5:-1}" "${6:-}" ;;
        update) jobs_update "${2:?job}" "${3:?campo}" "${4:?valor}" ;;
        remove) jobs_remove "${2:?job}" ;;
        enable) jobs_enable "${2:?job}" ;;
        disable) jobs_disable "${2:?job}" ;;
        *) echo "Uso: jobs.sh list|list-json|show|import|add|update|remove|enable|disable" >&2; exit 2 ;;
    esac
fi
