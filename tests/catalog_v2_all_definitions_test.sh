#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CATALOG_VIEW="$(mktemp -d)"
trap 'rm -rf -- "${CATALOG_VIEW}"' EXIT

cp -a "${ROOT}/catalog/v2/." "${CATALOG_VIEW}/"
while IFS= read -r deferred; do
  game_dir="$(dirname "$(dirname "${deferred}")")"
  game="$(basename "${game_dir}")"
  mkdir -p "${CATALOG_VIEW}/games/${game}/runtimes"
  cp -a "${deferred}" "${CATALOG_VIEW}/games/${game}/runtimes/$(basename "${deferred}")"
done < <(find "${ROOT}/catalog/v2/games" -path '*/deferred/*.json' -type f | sort)

DSM_CATALOG_ROOT="${CATALOG_VIEW}" bash "${ROOT}/tests/catalog_v2_all_definitions_impl.sh"
