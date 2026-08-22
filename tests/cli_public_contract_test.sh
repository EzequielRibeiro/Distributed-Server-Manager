#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

grep -Fq 'LEGACY_DSM="${DSM_ROOT}/bin/dsm-compat"' "${ROOT}/bin/cap"
grep -Fq '`cap` é a única CLI pública' "${ROOT}/bin/cap"
grep -Fq 'A única CLI pública do Capivara Distributed Server Manager é `cap`.' "${ROOT}/docs/architecture/cli-unification-v2.md"
! grep -Fq 'dsm user' "${ROOT}/core/user_manager.sh"
grep -Fq 'cap user add admin admin' "${ROOT}/core/user_manager.sh"
grep -Fq 'cap alerts open|ack|resolve|get|active|count|history' "${ROOT}/bin/cap"
grep -Fq 'alerts|alert) require_role "cap alerts" controller hybrid' "${ROOT}/bin/cap"
grep -Fq 'cap agent jobs show <job-id>' "${ROOT}/bin/cap"
grep -Fq 'cap agent update status|history|check' "${ROOT}/bin/cap"
grep -Fq 'cap database|db init|migrate|status|check|backup|restore' "${ROOT}/bin/cap"
grep -Fq 'cap server start|stop|restart|status|validate|publish' "${ROOT}/bin/cap"

grep -Fq "'dsm' foi descontinuado como CLI pública. Use 'cap'." "${ROOT}/bin/dsm"
grep -Fq 'exec "${DSM_ROOT}/bin/cap" "$@"' "${ROOT}/bin/dsm"
[[ -x "${ROOT}/bin/dsm-compat" ]]

printf '%s\n' 'CLI public contract: OK'
