#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

cat >"${TMP}/plan.json" <<'JSON'
{
  "schema_version":2,
  "kind":"InstallationPlan",
  "runtime":"dayz.stable",
  "operations":[
    {
      "content_id":"dayz.cf",
      "content_type":"mod",
      "target":"mods/@CF",
      "artifact":{"provider":"steam-workshop","package_id":"221100:1559212036"},
      "activation":{"adapter":"dayz","mode":"mod","mount_name":"@CF"}
    },
    {
      "content_id":"dayz.admin",
      "content_type":"mod",
      "target":"mods/@AdminTools",
      "artifact":{"provider":"steam-workshop","package_id":"221100:000000001"},
      "activation":{"adapter":"dayz","mode":"server-mod","mount_name":"@AdminTools"}
    }
  ]
}
JSON

RESULT="$(DSM_ROOT="${ROOT}" bash "${ROOT}/installer/content_activation.sh" render "${TMP}/plan.json" "${TMP}/instance")"
jq -e '
  .kind=="ContentActivation" and .runtime=="dayz.stable" and
  (.operations|length)==2 and
  (.operations[]|select(.parameter=="mod")|.value)=="-mod=mods/@CF" and
  (.operations[]|select(.parameter=="serverMod")|.value)=="-serverMod=mods/@AdminTools"
' <<<"${RESULT}" >/dev/null

cat >"${TMP}/unsafe.json" <<'JSON'
{"runtime":"dayz.stable","operations":[{"activation":{"adapter":"../../evil"}}]}
JSON
if DSM_ROOT="${ROOT}" bash "${ROOT}/installer/content_activation.sh" render "${TMP}/unsafe.json" "${TMP}/instance" >/dev/null 2>&1; then
    echo 'FAIL: unsafe adapter name accepted' >&2
    exit 1
fi

echo 'Content activation adapter tests passed.'
