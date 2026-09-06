#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COPIED="$(mktemp)"
cleanup(){
  while IFS= read -r target; do
    [[ -n "${target}" ]] && rm -f -- "${target}"
  done <"${COPIED}"
  rm -f -- "${COPIED}"
}
trap cleanup EXIT

while IFS= read -r deferred; do
  game_dir="$(dirname "$(dirname "${deferred}")")"
  game="$(basename "${game_dir}")"
  target_dir="${ROOT}/catalog/v2/games/${game}/runtimes"
  target="${target_dir}/$(basename "${deferred}")"
  [[ ! -e "${target}" ]] || {
    echo "FAIL: deferred staging would overwrite active runtime: ${target}" >&2
    exit 1
  }
  mkdir -p "${target_dir}"
  cp -a "${deferred}" "${target}"
  printf '%s\n' "${target}" >>"${COPIED}"
done < <(find "${ROOT}/catalog/v2/games" -path '*/deferred/*.json' -type f | sort)

bash "${ROOT}/tests/catalog_v2_all_definitions_impl.sh"
