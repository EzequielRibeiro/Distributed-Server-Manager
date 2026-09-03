#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT

BASE="${TMP}/spongevanilla"
FULL="1.21.8-16.0.0"
REMOTE="spongevanilla-${FULL}-universal.jar"
mkdir -p "${BASE}/${FULL}"
printf 'fixture' >"${BASE}/${FULL}/${REMOTE}"
sha256sum "${BASE}/${FULL}/${REMOTE}" | awk '{print $1}' >"${BASE}/${FULL}/${REMOTE}.sha256"
cat >"${BASE}/maven-metadata.xml" <<'XML'
<metadata>
  <groupId>org.spongepowered</groupId>
  <artifactId>spongevanilla</artifactId>
  <versioning>
    <versions>
      <version>1.21.8-16.0.0-RC2504</version>
      <version>1.21.8-16.0.0</version>
    </versions>
  </versioning>
</metadata>
XML

export SPONGE_MAVEN_BASE="file://${BASE}"
source "${ROOT}/installer/version_resolvers/sponge_maven.sh"

LIST="$(version_resolver_execute list minecraft spongevanilla '')"
jq -e '.variant == "spongevanilla" and ([.versions[] | select(.full == "1.21.8-16.0.0" and .stable == true)] | length) == 1' <<<"${LIST}" >/dev/null

RESOLVED="$(version_resolver_execute resolve minecraft spongevanilla '1.21.8')"
jq -e '.version == "1.21.8" and .build == "1.21.8-16.0.0" and .provider == "http" and .selected_asset.name == "server.jar" and .install.asset == "server.jar" and (.selected_asset.sha256 | length) == 64' <<<"${RESOLVED}" >/dev/null

PINNED="$(version_resolver_execute resolve minecraft spongevanilla '1.21.8@16.0.0')"
jq -e '.build == "1.21.8-16.0.0"' <<<"${PINNED}" >/dev/null

echo "Sponge Maven resolver tests passed."
