#!/usr/bin/env bash
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
JOBS="${DSM_ROOT}/scheduler/jobs.sh"
ENGINE="${DSM_ROOT}/scheduler/scheduler.sh"

usage()
{
cat >&2 <<'EOF'
Capivara Scheduler

Uso:
  cap scheduler list [--json]
  cap scheduler show JOB
  cap scheduler create --name NAME --schedule SCHEDULE --command COMMAND [--disabled]
  cap scheduler update JOB [--schedule SCHEDULE] [--command COMMAND]
  cap scheduler enable JOB
  cap scheduler disable JOB
  cap scheduler delete JOB
  cap scheduler run JOB [--force]
  cap scheduler status
  cap scheduler check

Schedules suportados:
  HH:MM        execução diária no horário local
  @hourly      a cada hora
  @daily       diariamente à meia-noite
  @weekly      segunda-feira à meia-noite
  @monthly     primeiro dia do mês à meia-noite
  @every:N     a cada N segundos
EOF
}

die(){ echo "Erro: $*" >&2; exit 2; }

cmd="${1:-}"; shift || true
case "${cmd}" in
    list)
        if [[ "${1:-}" == "--json" ]]; then exec "${JOBS}" list-json; fi
        exec "${JOBS}" list
        ;;
    show)
        [[ $# -eq 1 ]] || die "uso: cap scheduler show JOB"
        exec "${JOBS}" show "$1"
        ;;
    create)
        name=""; schedule=""; command=""; enabled=1
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --name) name="${2:-}"; shift 2 ;;
                --schedule) schedule="${2:-}"; shift 2 ;;
                --command) command="${2:-}"; shift 2 ;;
                --disabled) enabled=0; shift ;;
                -h|--help) usage; exit 0 ;;
                *) die "opção desconhecida: $1" ;;
            esac
        done
        [[ -n "${name}" && -n "${schedule}" && -n "${command}" ]] || die "--name, --schedule e --command são obrigatórios"
        "${JOBS}" add "${name}" "${schedule}" "${command}" "${enabled}" ""
        printf 'Job criado: %s\n' "${name}"
        ;;
    update)
        [[ $# -ge 1 ]] || die "JOB obrigatório"
        name="$1"; shift
        changed=0
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --schedule) "${JOBS}" update "${name}" schedule "${2:-}"; changed=1; shift 2 ;;
                --command) "${JOBS}" update "${name}" command "${2:-}"; changed=1; shift 2 ;;
                *) die "opção desconhecida: $1" ;;
            esac
        done
        [[ "${changed}" == "1" ]] || die "informe --schedule e/ou --command"
        printf 'Job atualizado: %s\n' "${name}"
        ;;
    enable)
        [[ $# -eq 1 ]] || die "JOB obrigatório"
        "${JOBS}" enable "$1"; printf 'Job ativado: %s\n' "$1"
        ;;
    disable)
        [[ $# -eq 1 ]] || die "JOB obrigatório"
        "${JOBS}" disable "$1"; printf 'Job desativado: %s\n' "$1"
        ;;
    delete|remove)
        [[ $# -eq 1 ]] || die "JOB obrigatório"
        "${JOBS}" remove "$1"; printf 'Job removido: %s\n' "$1"
        ;;
    run)
        [[ $# -ge 1 ]] || die "JOB obrigatório"
        name="$1"; shift; force=0
        [[ "${1:-}" != "--force" ]] || force=1
        exec "${ENGINE}" execute "${name}" "${force}"
        ;;
    status) exec "${ENGINE}" status ;;
    check) exec "${ENGINE}" check ;;
    -h|--help|help|"") usage ;;
    *) die "subcomando desconhecido: ${cmd}" ;;
esac
