#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT}/installer/version_resolvers/papermc.sh"

paper_get()
{
  case "$1" in
    */projects/folia)
      cat <<'JSON'
{"versions":{"26.2":["26.2"],"1.21":["1.21.11"]}}
JSON
      ;;
    */projects/folia/versions/26.2/builds)
      cat <<'JSON'
[
  {"id":12,"channel":"STABLE","downloads":{"server:default":{"name":"folia-26.2-12.jar","size":1234,"url":"https://example.invalid/folia.jar","checksums":{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}}},
  {"id":11,"channel":"EXPERIMENTAL","downloads":{"server:default":{"name":"folia-26.2-11.jar","size":1200,"url":"https://example.invalid/folia-old.jar","checksums":{"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}}}
]
JSON
      ;;
    */projects/paper/versions/26.2/builds)
      cat <<'JSON'
[
  {"id":48,"channel":"STABLE","downloads":{"server:default":{"name":"paper-26.2-48.jar","size":4321,"url":"https://example.invalid/paper.jar","checksums":{"sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}}}}
]
JSON
      ;;
    *) return 1 ;;
  esac
}

PAPERMC_PROJECT="folia"
GAME_ID="minecraft"
VARIANT_ID="folia"
LIST="$(version_resolver_execute list minecraft folia '')"
jq -e '.project=="folia" and .variant=="folia" and (.versions|map(.version)|index("26.2")!=null)' <<<"${LIST}" >/dev/null

FOLIA="$(version_resolver_execute resolve minecraft folia '26.2')"
jq -e '.project=="folia" and .build==12 and .channel=="STABLE" and .selected_asset.name=="server.jar" and .selected_asset.upstream_name=="folia-26.2-12.jar" and .install.asset=="server.jar" and .install.upstream_asset=="folia-26.2-12.jar"' <<<"${FOLIA}" >/dev/null

PINNED="$(version_resolver_execute resolve minecraft folia '26.2@11')"
jq -e '.build==11 and .selected_asset.name=="server.jar"' <<<"${PINNED}" >/dev/null

PAPERMC_PROJECT="paper"
VARIANT_ID="paper"
PAPER="$(version_resolver_execute resolve minecraft paper '26.2')"
jq -e '.project=="paper" and .selected_asset.name=="server.jar" and .selected_asset.upstream_name=="paper-26.2-48.jar" and .install.asset=="server.jar"' <<<"${PAPER}" >/dev/null

RUNTIME="${ROOT}/catalog/v2/games/minecraft/runtimes/java-folia.json"
jq -e '.id=="minecraft.java.folia" and .version.resolver=="papermc" and .version.config.project=="folia" and .process.executable=="server.jar" and .artifact.provider=="http" and (.requirements.os|sort)==["linux","windows"]' "${RUNTIME}" >/dev/null

MATRIX="${ROOT}/catalog/v2/support-matrix.json"
jq -e '.published_runtimes[] | select(.id=="minecraft.java.folia") | .resolver=="papermc" and (.content_ecosystems|index("folia-plugin")!=null)' "${MATRIX}" >/dev/null

echo "Folia catalog runtime tests passed."
