#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for marker in LEGACY_DSM legacy_exec dsm-compat; do
    ! grep -Fq "${marker}" "${ROOT}/bin/cap" \
        || { echo "retired compatibility marker remains in bin/cap: ${marker}" >&2; exit 1; }
done

grep -Fq '`cap` é a única CLI do Capivara DSM.' "${ROOT}/bin/cap"
grep -Fq 'A única CLI pública do Capivara Distributed Server Manager é `cap`.' "${ROOT}/docs/architecture/cli-unification-v2.md"
! grep -Fq 'dsm user' "${ROOT}/core/user_manager.sh"
grep -Fq 'cap user add admin admin' "${ROOT}/core/user_manager.sh"
grep -Fq 'cap alerts open|ack|resolve|get|active|count|history' "${ROOT}/bin/cap"
grep -Fq 'alerts|alert) require_role "cap alerts" controller hybrid' "${ROOT}/bin/cap"
grep -Fq 'cap agent jobs show <job-id>' "${ROOT}/bin/cap"
grep -Fq 'cap agent update status|history|check' "${ROOT}/bin/cap"
grep -Fq 'cap database|db init|migrate|status|check|backup|restore' "${ROOT}/bin/cap"
grep -Fq 'cap server start|stop|restart|status|validate|publish' "${ROOT}/bin/cap"
grep -Fq 'server) require_role "cap server" agent hybrid; shift; server_command "$@"' "${ROOT}/bin/cap"
grep -Fq 'backup) require_role "cap backup" agent hybrid; shift; backup_command "$@"' "${ROOT}/bin/cap"

[[ ! -e "${ROOT}/bin/dsm" ]]
[[ ! -e "${ROOT}/bin/dsm-compat" ]]

# Internal DSM_* identifiers, /opt/dsm, dsm_update_* and physical legacy names
# can remain where they are implementation details. Public help must not teach
# operators to invoke the retired dsm CLI.
! grep -Eq '(^|[[:space:]])dsm (server|doctor|monitor|mods|backup|config|update|steam|runtime|user|game|catalog|content|compatibility|agent|database|db|operations|ops|instance)([[:space:]]|$)' \
    "${ROOT}/bin/cap"
! grep -Eq '(^|[[:space:]])dsm-runtime([[:space:]]|$)' "${ROOT}/bin/dsm-runtime"

grep -Fq 'cap runtime publish <host> <game> <instance> <module> <json>' "${ROOT}/bin/dsm-runtime"
grep -Fq 'cap runtime get-resource <host> <game> <instance> <module>' "${ROOT}/bin/dsm-runtime"

printf '%s\n' 'CLI public contract: OK'
