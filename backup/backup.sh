#!/bin/bash
# =============================================================
# backup/backup.sh - MÓDULO 06
#
# Dispatcher Backup DSM
#
# =============================================================


set -euo pipefail


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


BACKUP_MODULE_DIR="${DSM_ROOT}/backup"


LOG_MODULE="backup"

# =============================================================
# Logger DSM
# =============================================================

if [[ -f "${DSM_ROOT}/core/logger.sh" ]]
then
    source "${DSM_ROOT}/core/logger.sh"
fi

# =============================================================
# Bootstrap DSM
# =============================================================

if [[ -f "${DSM_ROOT}/core/bootstrap.sh" ]]
then
    source "${DSM_ROOT}/core/bootstrap.sh"
fi



case "${1:-}" in


create)

    exec "${BACKUP_MODULE_DIR}/create.sh" create

;;


snapshot)

    exec "${BACKUP_MODULE_DIR}/snapshot.sh" create

;;


list)

    exec "${BACKUP_MODULE_DIR}/create.sh" list

;;


snapshot-list)

    exec "${BACKUP_MODULE_DIR}/snapshot.sh" list

;;


restore)

    shift

    exec "${BACKUP_MODULE_DIR}/restore.sh" "$@"

;;


*)

echo
echo "DSM Backup"
echo
echo "Uso:"
echo
echo " backup.sh create"
echo " backup.sh snapshot"
echo " backup.sh list"
echo " backup.sh snapshot-list"
echo " backup.sh restore arquivo.tar.gz"
echo

exit 1

;;


esac