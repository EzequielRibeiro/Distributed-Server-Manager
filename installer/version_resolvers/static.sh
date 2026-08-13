#!/usr/bin/env bash
# Capivara DSM - Static Version Resolver v1
set -Eeuo pipefail

version_resolver_execute()
{
    local ACTION="$1" GAME="$2" VARIANT="$3" SELECTOR="${4:-}"
    local VALUES="${STATIC_VERSIONS:-}"
    local JSON='[]' V

    for V in $VALUES; do
        JSON="$(jq -c --arg v "$V" '. + [{version:$v,build:$v}]' <<<"$JSON")"
    done

    case "$ACTION" in
      list)
        jq -nc --arg game "$GAME" --arg variant "$VARIANT" --argjson versions "$JSON" \
          '{game:$game,variant:$variant,source:"static",versions:$versions}'
        ;;
      resolve)
        jq -nc --arg s "$SELECTOR" --argjson versions "$JSON" '
          ($versions|map(select(.version==$s or .build==$s))|first) as $r |
          if $r==null then {error:"version_not_found",selector:$s} else $r end'
        ;;
      *) return 2 ;;
    esac
}

export -f version_resolver_execute
