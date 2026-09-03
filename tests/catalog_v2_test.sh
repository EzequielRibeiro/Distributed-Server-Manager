#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DSM_ROOT="${ROOT}"

fail(){ echo "FAIL: $*" >&2; exit 1; }

RUNTIMES="$("${ROOT}/installer/catalog.sh" runtime list minecraft --json)"
[[ "$(jq 'length' <<<"${RUNTIMES}")" -eq 6 ]] || fail "expected six installable Minecraft environments"
jq -e 'map(.id) | index("minecraft.bedrock.vanilla") != null' <<<"${RUNTIMES}" >/dev/null || fail "Bedrock runtime missing"
jq -e 'map(.id) | index("minecraft.java.forge") != null' <<<"${RUNTIMES}" >/dev/null || fail "Forge runtime missing"

ALL_RUNTIMES="$("${ROOT}/installer/catalog.sh" runtime list --json)"
jq -e 'map(.id) | index("arma3.stable") != null' <<<"${ALL_RUNTIMES}" >/dev/null || fail "Arma 3 environment missing"
jq -e 'map(.id) | index("dayz.stable") != null' <<<"${ALL_RUNTIMES}" >/dev/null || fail "DayZ environment missing"
jq -e 'map(.id) | index("rust.stable") != null' <<<"${ALL_RUNTIMES}" >/dev/null || fail "Rust environment missing"
jq -e 'map(.id) | index("mindustry.github") != null' <<<"${ALL_RUNTIMES}" >/dev/null || fail "GitHub environment missing"
jq -e 'all(.[];
  .schema_version==2 and .kind=="RuntimeDefinition" and
  (.version.strategy=="static" or .version.strategy=="dynamic") and
  (.process.executable|length)>0 and (.requirements.os|length)>0 and
  (.requirements.architectures|length)>0 and
  (.installation.directory|startswith("/")) and
  (if .artifact.provider=="steam" then (.artifact.package_id|length)>0
   elif .artifact.provider=="github" then (.artifact.repository|length)>0
   elif .artifact.provider=="http" and .version.strategy=="static" then (.artifact.url|startswith("https://"))
   else true end))' <<<"${ALL_RUNTIMES}" >/dev/null || fail "execution environment contract invalid"

RUST_SELECTION="$("${ROOT}/installer/catalog.sh" runtime prepare rust.stable current --json)"
jq -e '.schema_version==2 and .kind=="RuntimeSelection" and .provider=="steam" and .install.package_id=="258550"' \
  <<<"${RUST_SELECTION}" >/dev/null || fail "Steam selection is not generated from the canonical catalog"

HTTP_SELECTION="$("${ROOT}/installer/catalog.sh" runtime prepare minecraft.java.vanilla latest --json)"
jq -e '.schema_version==2 and .provider=="http" and (.install.url|startswith("https://")) and .executable=="server.jar"' \
  <<<"${HTTP_SELECTION}" >/dev/null || fail "HTTP selection is not generated from the canonical catalog"

INSTALL_SELECTION="$(DSM_ROOT="${ROOT}" "${ROOT}/installer/install_selection.sh" show dayz.stable current)"
jq -e '.schema_version==2 and .auth=="required" and .install.package_id=="223350"' \
  <<<"${INSTALL_SELECTION}" >/dev/null || fail "installation adapter does not consume canonical selections"
grep -Fq 'INSTALL_USER="anonymous"' "${ROOT}/installer/install_selection.sh" \
  || fail "anonymous Steam catalog environments do not use anonymous login"
grep -Fq 'DSM_STEAM_USER' "${ROOT}/installer/install_selection.sh" \
  || fail "authenticated Steam environments do not require a prepared account"

[[ ! -e "${ROOT}/games/catalog.json" ]] || fail "legacy game catalog still exists"
[[ ! -e "${ROOT}/installer/version_discovery.sh" ]] || fail "legacy version discovery still exists"
[[ ! -e "${ROOT}/installer/catalog_v2.sh" ]] || fail "duplicate catalog entrypoint still exists"

CONTENT="$("${ROOT}/installer/catalog.sh" content list minecraft --json)"
[[ "$(jq 'length' <<<"${CONTENT}")" -eq 3 ]] || fail "expected mod, plugin and modpack examples"
jq -e 'map(.content_type) | sort == ["mod","modpack","plugin"]' <<<"${CONTENT}" >/dev/null || fail "content types missing"

API_RUNTIMES="$(bash "${ROOT}/dashboard/api/catalog.sh" runtimes minecraft)"
[[ "$(jq 'length' <<<"${API_RUNTIMES}")" -eq 6 ]] || fail "dashboard API runtime adapter invalid"
API_CONTENT="$(bash "${ROOT}/dashboard/api/catalog.sh" content minecraft)"
[[ "$(jq 'length' <<<"${API_CONTENT}")" -eq 3 ]] || fail "dashboard API content adapter invalid"
API_COMPATIBILITY="$(bash "${ROOT}/dashboard/api/catalog.sh" compatibility "${ROOT}/catalog/v2/examples/compatibility-allowed.json")"
jq -e '.compatible == true' <<<"${API_COMPATIBILITY}" >/dev/null || fail "dashboard API compatibility adapter invalid"

ALLOWED="$("${ROOT}/installer/compatibility_resolver.sh" check "${ROOT}/catalog/v2/examples/compatibility-allowed.json")"
jq -e '.compatible == true and .decision == "INSTALL_ALLOWED"' <<<"${ALLOWED}" >/dev/null || fail "allowed case blocked"

BLOCKED="$("${ROOT}/installer/compatibility_resolver.sh" check "${ROOT}/catalog/v2/examples/compatibility-blocked.json")"
jq -e '.compatible == false and .decision == "INSTALL_BLOCKED" and (.errors|map(.code)|index("loader") != null)' <<<"${BLOCKED}" >/dev/null || fail "blocked case allowed"

TMP_COMPATIBILITY="$(mktemp -d)"
trap 'rm -rf -- "${TMP_COMPATIBILITY}"' EXIT
jq '.runtime.id="minecraft.java.arclight" | .runtime.loader="arclight" | .content=["minecraft.example.plugin"]' \
  "${ROOT}/catalog/v2/examples/compatibility-allowed.json" >"${TMP_COMPATIBILITY}/arclight-plugin.json"
ARCLIGHT_PLUGIN="$("${ROOT}/installer/compatibility_resolver.sh" check "${TMP_COMPATIBILITY}/arclight-plugin.json")"
jq -e '.compatible == true and (.errors|length)==0' <<<"${ARCLIGHT_PLUGIN}" >/dev/null || fail "empty loader version rules blocked Arclight plugin"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_COMPATIBILITY}" "${TMP_DIR}"' EXIT
mkdir -p "${TMP_DIR}/catalog/games" "${TMP_DIR}/catalog/content/minecraft" "${TMP_DIR}/instance"
cp -a "${ROOT}/catalog/v2/games/." "${TMP_DIR}/catalog/games/"
jq '.artifact.package_id="tests/fixtures/example-mod.jar"' \
  "${ROOT}/catalog/v2/content/minecraft/example-mod.json" >"${TMP_DIR}/catalog/content/minecraft/example-mod.json"
jq '.id="minecraft.example.addon"|.name="Example Addon"|.artifact.package_id="tests/fixtures/example-mod.jar"|.dependencies=[{id:"minecraft.example.mod",version:">=1.0.0",required:true}]' \
  "${ROOT}/catalog/v2/content/minecraft/example-mod.json" >"${TMP_DIR}/catalog/content/minecraft/example-addon.json"
INSTALLED_EMPTY="$("${ROOT}/installer/content_manager.sh" list-installed "${TMP_DIR}/instance")"
jq -e --arg instance "${TMP_DIR}/instance" '
  .instance == $instance and .entries == [] and .content == [] and .installed == [] and .total == 0
' <<<"${INSTALLED_EMPTY}" >/dev/null || fail "empty content list-installed response expected for instance without content-lock"
export DSM_CATALOG_ROOT="${TMP_DIR}/catalog"
install_operation_progress_safe(){ :; }
export -f install_operation_progress_safe

PLAN="$("${ROOT}/installer/content_planner.sh" plan "${ROOT}/catalog/v2/examples/compatibility-allowed.json" "${TMP_DIR}/instance")"
jq -e '.kind=="InstallationPlan" and (.operations|length)==1' <<<"${PLAN}" >/dev/null || fail "installation plan invalid"

"${ROOT}/installer/content_manager.sh" install "${ROOT}/catalog/v2/examples/compatibility-allowed.json" "${TMP_DIR}/instance" >/dev/null
"${ROOT}/installer/content_manager.sh" verify "${TMP_DIR}/instance" >/dev/null
jq -e '.entries|length==1' "${TMP_DIR}/instance/content/.dsm/content-lock.json" >/dev/null || fail "content lock invalid"
jq -e '.content==["minecraft.example.mod"]' "${TMP_DIR}/instance/.dsm/instance-manifest.json" >/dev/null || fail "instance manifest invalid"

"${ROOT}/installer/content_manager.sh" remove "${TMP_DIR}/instance" minecraft.example.mod >/dev/null
jq -e '.entries|length==0' "${TMP_DIR}/instance/content/.dsm/content-lock.json" >/dev/null || fail "content removal failed"
jq -e '.content|length==0' "${TMP_DIR}/instance/.dsm/instance-manifest.json" >/dev/null || fail "manifest removal state invalid"
"${ROOT}/installer/content_manager.sh" rollback "${TMP_DIR}/instance" >/dev/null
"${ROOT}/installer/content_manager.sh" verify "${TMP_DIR}/instance" >/dev/null
jq -e '.entries|length==1' "${TMP_DIR}/instance/content/.dsm/content-lock.json" >/dev/null || fail "content rollback failed"
jq -e '.content==["minecraft.example.mod"]' "${TMP_DIR}/instance/.dsm/instance-manifest.json" >/dev/null || fail "rollback manifest invalid"

jq '.content=["minecraft.example.addon"]' "${ROOT}/catalog/v2/examples/compatibility-allowed.json" >"${TMP_DIR}/addon-request.json"
ADDON_PLAN="$("${ROOT}/installer/content_planner.sh" plan "${TMP_DIR}/addon-request.json" "${TMP_DIR}/instance")"
jq -e '.operations|map(.content_id)==["minecraft.example.mod","minecraft.example.addon"]' <<<"${ADDON_PLAN}" >/dev/null || fail "transitive dependency order invalid"
"${ROOT}/installer/content_manager.sh" install "${TMP_DIR}/addon-request.json" "${TMP_DIR}/instance" >/dev/null
jq -e '.entries|length==2' "${TMP_DIR}/instance/content/.dsm/content-lock.json" >/dev/null || fail "incremental lock merge failed"
if "${ROOT}/installer/content_manager.sh" remove "${TMP_DIR}/instance" minecraft.example.mod >/dev/null 2>&1; then fail "required dependency removal allowed"; fi

jq '.dependencies[0].version=">=2.0.0"' "${TMP_DIR}/catalog/content/minecraft/example-addon.json" >"${TMP_DIR}/addon-v2.json"
mv -- "${TMP_DIR}/addon-v2.json" "${TMP_DIR}/catalog/content/minecraft/example-addon.json"
jq '.content=["minecraft.example.mod","minecraft.example.addon"]' "${ROOT}/catalog/v2/examples/compatibility-allowed.json" >"${TMP_DIR}/dependency-version.json"
VERSION_RESULT="$("${ROOT}/installer/compatibility_resolver.sh" check "${TMP_DIR}/dependency-version.json")"
jq -e '.errors|map(.code)|index("dependency_version") != null' <<<"${VERSION_RESULT}" >/dev/null || fail "dependency version mismatch not detected"

jq '.id="cycle.a"|.artifact.package_id="tests/fixtures/example-mod.jar"|.dependencies=[{id:"cycle.b",version:null,required:true}]' \
  "${ROOT}/catalog/v2/content/minecraft/example-mod.json" >"${TMP_DIR}/catalog/content/minecraft/cycle-a.json"
jq '.id="cycle.b"|.artifact.package_id="tests/fixtures/example-mod.jar"|.dependencies=[{id:"cycle.a",version:null,required:true}]' \
  "${ROOT}/catalog/v2/content/minecraft/example-mod.json" >"${TMP_DIR}/catalog/content/minecraft/cycle-b.json"
jq '.content=["cycle.a"]' "${ROOT}/catalog/v2/examples/compatibility-allowed.json" >"${TMP_DIR}/cycle-request.json"
if "${ROOT}/installer/content_planner.sh" plan "${TMP_DIR}/cycle-request.json" "${TMP_DIR}/instance" >/dev/null 2>&1; then fail "dependency cycle allowed"; fi

export DSM_CATALOG_ROOT="${ROOT}/catalog/v2"
jq '. + {content:["minecraft.example.modpack"]}' "${ROOT}/catalog/v2/examples/compatibility-blocked.json" >"${TMP_DIR}/dependency-missing.json"
MISSING="$("${ROOT}/installer/compatibility_resolver.sh" check "${TMP_DIR}/dependency-missing.json")"
jq -e '.errors|map(.code)|index("dependency_missing") != null' <<<"${MISSING}" >/dev/null || fail "missing dependency not detected"

echo "Canonical catalog tests passed."
