#!/usr/bin/env bash
# Capivara DSM - DayZ content activation adapter
set -Eeuo pipefail

content_adapter_render()
{
    local PLAN="${1:-}" INSTANCE="${2:-}"
    local MOD_PATHS SERVER_MOD_PATHS

    MOD_PATHS="$(jq -r '
      [.operations[]? |
       select(.activation.adapter=="dayz" and ((.activation.mode // "mod")=="mod")) |
       .target] | unique | join(";")' "${PLAN}" | tr -d '\r')"
    SERVER_MOD_PATHS="$(jq -r '
      [.operations[]? |
       select(.activation.adapter=="dayz" and (.activation.mode // "")=="server-mod") |
       .target] | unique | join(";")' "${PLAN}" | tr -d '\r')"

    jq -n \
      --arg mods "${MOD_PATHS}" \
      --arg servermods "${SERVER_MOD_PATHS}" '
      [
        (if $mods!="" then {
          kind:"process_argument",
          owner:"content",
          game:"dayz",
          parameter:"mod",
          value:("-mod="+$mods),
          content_paths:($mods|split(";"))
        } else empty end),
        (if $servermods!="" then {
          kind:"process_argument",
          owner:"content",
          game:"dayz",
          parameter:"serverMod",
          value:("-serverMod="+$servermods),
          content_paths:($servermods|split(";"))
        } else empty end)
      ]'
}

export -f content_adapter_render
