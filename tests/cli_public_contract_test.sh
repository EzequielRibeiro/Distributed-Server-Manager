#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

grep -Fq 'LEGACY_DSM="${DSM_ROOT}/bin/dsm-compat"' "${ROOT}/bin/cap"
grep -Fq '`cap` é a única CLI pública' "${ROOT}/bin/cap"
grep -Fq 'A única CLI pública do Capivara Distributed Server Manager é `cap`.' "${ROOT}/docs/architecture/cli-unification-v2.md"

# The public DSM help must explicitly identify itself as compatibility-only
# until the final wrapper inversion is completed.
grep -Fq 'CLI DSM de compatibilidade / baixo nível' "${ROOT}/bin/dsm"

printf '%s\n' 'CLI public contract: OK'
