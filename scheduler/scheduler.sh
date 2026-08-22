#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
SCHEDULER_DIR="${DSM_ROOT}/scheduler"
TASK_DIR="${SCHEDULER_DIR}/tasks"
LOG_FILE="${DSM_ROOT}/logs/scheduler.log"

# shellcheck source=/dev/null
source "${SCHEDULER_DIR}/executor.sh"
# shellcheck source=/dev/null
source "${SCHEDULER_DIR}/history.sh"
# shellcheck source=/dev/null
source "${SCHEDULER_DIR}/cron_engine.sh"
# shellcheck source=/dev/null
source "${SCHEDULER_DIR}/jobs.sh"

scheduler_log(){ mkdir -p "$(dirname "${LOG_FILE}")"; printf '%s - %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"${LOG_FILE}"; }

scheduler_import_tasks(){ jobs_import_tasks; }

scheduler_last_run_epoch()
{
    local value="${1:-}"
    [[ -n "${value}" && "${value}" != "null" ]] || { echo 0; return; }
    date -d "${value}" +%s 2>/dev/null || echo 0
}

scheduler_due_job()
{
    local schedule="$1" last_run_at="${2:-}"
    local now last; now="$(date +%s)"; last="$(scheduler_last_run_epoch "${last_run_at}")"
    case "${schedule}" in
        @every:*)
            local interval="${schedule#@every:}"
            (( now - last >= interval ))
            ;;
        *)
            cron_match "${schedule}" || return 1
            # Avoid a second execution inside the same scheduler minute.
            (( now - last >= 60 ))
            ;;
    esac
}

scheduler_execute_job()
{
    local name="$1" force="${2:-0}"
    local data enabled command
    data="$(jobs_show "${name}")"
    [[ -n "${data}" ]] || { scheduler_log "Job inexistente: ${name}"; echo "Erro: job inexistente: ${name}" >&2; return 2; }
    enabled="$(jq -r '.enabled' <<<"${data}")"
    command="$(jq -r '.command' <<<"${data}")"
    if [[ "${enabled}" != "1" && "${force}" != "1" ]]; then
        echo "Erro: job desabilitado: ${name}" >&2
        return 2
    fi
    scheduler_log "Executando job: ${name}"
    if executor_run "${name}" "${command}"; then
        jobs_mark_run "${name}" success
        scheduler_log "Job concluído: ${name}"
        return 0
    fi
    local rc=$?
    jobs_mark_run "${name}" failed || true
    scheduler_log "Job falhou (${rc}): ${name}"
    return "${rc}"
}

scheduler_check()
{
    jobs_init || return 1
    local job name schedule enabled last_run
    while IFS= read -r job; do
        name="$(jq -r '.name' <<<"${job}")"
        schedule="$(jq -r '.schedule' <<<"${job}")"
        enabled="$(jq -r '.enabled' <<<"${job}")"
        last_run="$(jq -r '.last_run_at // ""' <<<"${job}")"
        [[ "${enabled}" == "1" ]] || continue
        if scheduler_due_job "${schedule}" "${last_run}"; then
            scheduler_execute_job "${name}" || true
        fi
    done < <(jq -c '.jobs[]' "${JOBS_DB}")
}

scheduler_run()
{
    scheduler_log "Scheduler iniciado"
    scheduler_import_tasks
    while true; do scheduler_check; sleep 60; done
}

scheduler_status()
{
    jobs_init || return 1
    local total enabled
    total="$(jq '.jobs|length' "${JOBS_DB}")"
    enabled="$(jq '[.jobs[]|select(.enabled==1)]|length' "${JOBS_DB}")"
    printf 'Capivara Scheduler\nJobs: %s\nAtivos: %s\nDatabase: %s\nEstado: ONLINE\n' "${total}" "${enabled}" "${JOBS_DB}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-}" in
        run) scheduler_run ;;
        check) scheduler_check ;;
        import) scheduler_import_tasks ;;
        status) scheduler_status ;;
        execute) scheduler_execute_job "${2:?job obrigatório}" "${3:-0}" ;;
        *) echo "Uso: scheduler.sh run|check|import|status|execute JOB [force]" >&2; exit 2 ;;
    esac
fi
