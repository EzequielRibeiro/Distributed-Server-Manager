#!/bin/bash
# =============================================================
# mods/mods.sh - MÓDULO 03 (MODS)
#
# Dispatcher principal do módulo de Mods DSM
# Main dispatcher for the DSM Mods module
#
# Responsável por: | Responsible for:
# - receber comandos: dsm mods <comando> | receiving commands: dsm mods <command>
# - carregar módulos | loading modules
# - encaminhar execução | routing execution
#
# NÃO FAZ: | DOES NOT DO:
# - SteamCMD
# - rsync
# - instalação | installation
# - atualização | update
# - backup
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap DSM
# =============================================================
source "${DSM_ROOT}/core/bootstrap.sh"

# Garantir logger | Ensure logger
if ! declare -F log_error >/dev/null
then
    source "${DSM_ROOT}/core/logger.sh"
fi

# =============================================================
# Carregar pipeline | Load pipeline
# =============================================================
source "${DSM_ROOT}/mods/pipeline.sh"

# =============================================================
# Serviços Mods | Mods Services
# =============================================================
source "${DSM_ROOT}/mods/status.sh"
source "${DSM_ROOT}/mods/state.sh"
source "${DSM_ROOT}/mods/backup.sh"
source "${DSM_ROOT}/mods/cleanup.sh"
source "${DSM_ROOT}/mods/export.sh"
source "${DSM_ROOT}/mods/import.sh"
source "${DSM_ROOT}/mods/api.sh"
source "${DSM_ROOT}/mods/log.sh"

# =============================================================
# Ajuda | Help
# =============================================================
mods_usage()
{
cat <<EOF

DSM Mods

Uso | Usage:

 dsm mods <comando | command>

Instalação | Installation:

 dsm mods install

Atualização | Update:

 dsm mods update

Validação | Validation:

 dsm mods verify

Rollback:

 dsm mods rollback <ID>

Estado | State:

 dsm mods state

Status:

 dsm mods status

Saúde | Health:

 dsm mods health

Relatório | Report:

 dsm mods report

Backup:

 dsm mods backup

Limpeza | Cleanup:

 dsm mods cleanup

Exportar | Export:

 dsm mods export

Importar | Import:

 dsm mods import

API:

 dsm mods api

Logs:

 dsm mods log

Keys:

 dsm mods keys

EOF
}

# =============================================================
# Dispatcher
# =============================================================
mods_command()
{
case "${1:-}" in
    install)
        mods_pipeline_install
    ;;
    update)
        shift
        mods_pipeline_update "$@"
    ;;
    verify)
        mods_pipeline_verify
    ;;
    rollback)
        shift
        mods_pipeline_rollback "$@"
    ;;
    keys)
        mods_pipeline_keys
    ;;
    state)
        mods_pipeline_state
    ;;
    status)
        mods_status_show
    ;;
    health)
        mods_health
    ;;
    report)
        mods_report
    ;;
    backup)
        shift
            mods_backup "$@"
    ;;
    cleanup)
        mods_cleanup "$@"
    ;;
   sync)
       state_sync_from_workshop
   ;;
    export)
        mods_export "$@"
    ;;
    import)
        mods_import "$@"
    ;;
    api)
        mods_api "$@"
    ;;
    log)
        mods_log "$@"
    ;;
    *)
        mods_usage
        return 1
    ;;
esac
}

# =============================================================
# Execução direta | Direct execution
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    mods_command "$@"
fi
