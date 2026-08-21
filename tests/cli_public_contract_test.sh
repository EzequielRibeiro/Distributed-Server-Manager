#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

grep -Fq 'LEGACY_DSM="${DSM_ROOT}/bin/dsm-compat"' "${ROOT}/bin/cap"
grep -Fq '`cap` é a única CLI pública' "${ROOT}/bin/cap"
grep -Fq 'A única CLI pública do Capivara Distributed Server Manager é `cap`.' "${ROOT}/docs/architecture/cli-unification-v2.md"

grep -Fq "'dsm' foi descontinuado como CLI pública. Use 'cap'." "${ROOT}/bin/dsm"
grep -Fq 'exec "${DSM_ROOT}/bin/cap" "$@"' "${ROOT}/bin/dsm"
[[ -x "${ROOT}/bin/dsm-compat" ]]

printf '%s\n' 'CLI public contract: OK'
