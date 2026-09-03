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

cat >"${TMP}/zomboid.json" <<'JSON'
{
  "schema_version":2,
  "kind":"InstallationPlan",
  "runtime":"project-zomboid.stable",
  "operations":[
    {
      "content_id":"project-zomboid.example-one",
      "content_type":"mod",
      "target":"mods/example-one",
      "artifact":{
        "provider":"steam-workshop",
        "package_id":"108600:1234567890",
        "workshop_app_id":"108600",
        "published_file_id":"1234567890"
      },
      "activation":{"adapter":"project-zomboid","identifier":"ExampleModOne"}
    },
    {
      "content_id":"project-zomboid.example-two",
      "content_type":"mod",
      "target":"mods/example-two",
      "artifact":{
        "provider":"steam-workshop",
        "package_id":"108600:9876543210",
        "workshop_app_id":"108600",
        "published_file_id":"9876543210"
      },
      "activation":{"adapter":"project-zomboid","identifier":"ExampleModTwo"}
    }
  ]
}
JSON

RESULT="$(DSM_ROOT="${ROOT}" bash "${ROOT}/installer/content_activation.sh" render "${TMP}/zomboid.json" "${TMP}/instance")"
jq -e '
  .kind=="ContentActivation" and .runtime=="project-zomboid.stable" and
  (.operations|length)==2 and
  (.operations[]|select(.parameter=="WorkshopItems")|.kind)=="configuration_property" and
  (.operations[]|select(.parameter=="WorkshopItems")|.value)=="1234567890;9876543210" and
  (.operations[]|select(.parameter=="Mods")|.value)=="ExampleModOne;ExampleModTwo" and
  (.operations[]|select(.parameter=="Mods")|.configuration)=="server-ini"
' <<<"${RESULT}" >/dev/null

cat >"${TMP}/zomboid-invalid.json" <<'JSON'
{
  "runtime":"project-zomboid.stable",
  "operations":[
    {
      "content_id":"project-zomboid.invalid",
      "artifact":{
        "provider":"steam-workshop",
        "package_id":"221100:1234567890",
        "workshop_app_id":"221100",
        "published_file_id":"1234567890"
      },
      "activation":{"adapter":"project-zomboid","identifier":"Bad;Mod"}
    }
  ]
}
JSON
if DSM_ROOT="${ROOT}" bash "${ROOT}/installer/content_activation.sh" render "${TMP}/zomboid-invalid.json" "${TMP}/instance" >/dev/null 2>&1; then
    echo 'FAIL: invalid Project Zomboid activation accepted' >&2
    exit 1
fi

cat >"${TMP}/unsafe.json" <<'JSON'
{"runtime":"dayz.stable","operations":[{"activation":{"adapter":"../../evil"}}]}
JSON
if DSM_ROOT="${ROOT}" bash "${ROOT}/installer/content_activation.sh" render "${TMP}/unsafe.json" "${TMP}/instance" >/dev/null 2>&1; then
    echo 'FAIL: unsafe adapter name accepted' >&2
    exit 1
fi

echo 'Content activation adapter tests passed.'
