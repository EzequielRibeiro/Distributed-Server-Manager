#!/usr/bin/env bash
# Capivara DSM - Project Zomboid content activation adapter
set -Eeuo pipefail

content_adapter_render()
{
    local PLAN="${1:-}" INSTANCE="${2:-}"
    local INVALID WORKSHOP_ITEMS MOD_IDS CONTENT_IDS

    INVALID="$(jq -r '
      [.operations[]? |
       select(.activation.adapter=="project-zomboid") |
       {
         workshop_app_id:(.artifact.workshop_app_id // ((.artifact.package_id // "")|split(":")|.[0] // "") | tostring),
         published_file_id:(.artifact.published_file_id // ((.artifact.package_id // "")|split(":")|.[1] // "") | tostring),
         mod_id:(.activation.identifier // "" | tostring)
       } |
       select(
         (.workshop_app_id != "108600") or
         (.published_file_id | test("^[0-9]+$") | not) or
         (.mod_id == "") or
         (.mod_id | test("[;\\r\\n]") )
       )] | length' "${PLAN}" | tr -d '\r')"

    [[ "${INVALID}" == "0" ]] || {
        echo "[DSM][CONTENT-ACTIVATION][ERROR] Project Zomboid content requires Workshop AppID 108600, a numeric PublishedFileId, and a safe activation.identifier Mod ID." >&2
        return 1
    }

    WORKSHOP_ITEMS="$(jq -r '
      [.operations[]? |
       select(.activation.adapter=="project-zomboid") |
       (.artifact.published_file_id // ((.artifact.package_id // "")|split(":")|.[1] // "") | tostring)] |
      reduce .[] as $v ([]; if index($v) then . else . + [$v] end) |
      join(";")' "${PLAN}" | tr -d '\r')"

    MOD_IDS="$(jq -r '
      [.operations[]? |
       select(.activation.adapter=="project-zomboid") |
       (.activation.identifier | tostring)] |
      reduce .[] as $v ([]; if index($v) then . else . + [$v] end) |
      join(";")' "${PLAN}" | tr -d '\r')"

    CONTENT_IDS="$(jq -c '
      [.operations[]? |
       select(.activation.adapter=="project-zomboid") |
       .content_id] |
      reduce .[] as $v ([]; if index($v) then . else . + [$v] end)' "${PLAN}" | tr -d '\r')"

    jq -n \
      --arg workshop "${WORKSHOP_ITEMS}" \
      --arg mods "${MOD_IDS}" \
      --argjson content_ids "${CONTENT_IDS}" '
      [
        (if $workshop!="" then {
          kind:"configuration_property",
          owner:"content",
          game:"project-zomboid",
          configuration:"server-ini",
          parameter:"WorkshopItems",
          value:$workshop,
          delimiter:";",
          content_ids:$content_ids
        } else empty end),
        (if $mods!="" then {
          kind:"configuration_property",
          owner:"content",
          game:"project-zomboid",
          configuration:"server-ini",
          parameter:"Mods",
          value:$mods,
          delimiter:";",
          content_ids:$content_ids
        } else empty end)
      ]'
}

export -f content_adapter_render
