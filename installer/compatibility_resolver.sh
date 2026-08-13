#!/usr/bin/env bash
# Capivara DSM - Basic CompatibilityResolver v2
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DSM_ROOT="${DSM_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CATALOG_ROOT="${DSM_CATALOG_ROOT:-${DSM_ROOT}/catalog/v2}"

compatibility_error(){ echo "[DSM][COMPATIBILITY][ERROR] $*" >&2; }

compatibility_check()
{
    local REQUEST="$1" TMP_DIR RUNTIMES CONTENT
    [[ -f "${REQUEST}" ]] || { compatibility_error "Request not found: ${REQUEST}"; return 2; }
    jq -e '.schema_version == 2 and (.runtime|type == "object") and (.environment|type == "object") and (.content|type == "array")' "${REQUEST}" >/dev/null || {
        compatibility_error "Invalid CompatibilityRequest."
        return 2
    }

    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf -- "${TMP_DIR}"' RETURN
    RUNTIMES="${TMP_DIR}/runtimes.json"
    CONTENT="${TMP_DIR}/content.json"
    find "${CATALOG_ROOT}/runtimes" -type f -name '*.json' -print0 | xargs -0 -r jq -s '.' >"${RUNTIMES}"
    find "${CATALOG_ROOT}/content" -type f -name '*.json' -print0 | xargs -0 -r jq -s '.' >"${CONTENT}"

    jq -n --slurpfile req "${REQUEST}" --slurpfile runtimes "${RUNTIMES}" --slurpfile definitions "${CONTENT}" '
      def nums: split(".") | map(sub("[^0-9].*$"; "") | tonumber? // 0) | . + [0,0,0] | .[0:3];
      def version_ok($actual; $rule):
        if ($rule == null or $rule == "" or $actual == null) then true
        elif ($rule|startswith(">=")) then (($actual|nums) >= ($rule[2:]|nums))
        elif ($rule|startswith("<=")) then (($actual|nums) <= ($rule[2:]|nums))
        elif ($rule|startswith(">")) then (($actual|nums) > ($rule[1:]|nums))
        elif ($rule|startswith("<")) then (($actual|nums) < ($rule[1:]|nums))
        elif ($rule|startswith("=")) then (($actual|nums) == ($rule[1:]|nums))
        else (($actual|nums) == ($rule|nums)) end;
      def accepts($values; $actual): ($values == null or ($values|length)==0 or ($values|index($actual)) != null);
      def err($code; $content; $expected; $actual): {code:$code,content:$content,expected:$expected,actual:$actual};

      $req[0] as $q |
      $runtimes[0] as $rs |
      $definitions[0] as $defs |
      ($rs | map(select(.id == $q.runtime.id)) | first) as $runtime |
      ($defs | map(select(.id as $id | $q.content | index($id)))) as $selected |
      (($q.content + ($q.installed_content // [])) | unique) as $available |
      ([
        if $runtime == null then err("runtime_not_found";$q.runtime.id;"known runtime";null) else empty end,
        if $runtime != null and $runtime.game != $q.runtime.game then err("runtime_game";$runtime.id;$runtime.game;$q.runtime.game) else empty end,
        if $runtime != null and $runtime.edition != $q.runtime.edition then err("runtime_edition";$runtime.id;$runtime.edition;$q.runtime.edition) else empty end,
        if $runtime != null and ($runtime.requirements.os|index($q.environment.os)) == null then err("runtime_os";$runtime.id;$runtime.requirements.os;$q.environment.os) else empty end,
        if $runtime != null and ($runtime.requirements.architectures|index($q.environment.architecture)) == null then err("runtime_architecture";$runtime.id;$runtime.requirements.architectures;$q.environment.architecture) else empty end,
        if $runtime != null and $runtime.requirements.java != null and ($q.environment.java == null or $q.environment.java < $runtime.requirements.java.min or $q.environment.java > $runtime.requirements.java.max) then err("runtime_java";$runtime.id;$runtime.requirements.java;$q.environment.java) else empty end,
        ($q.content[] as $id | if ($defs|map(.id)|index($id)) == null then err("content_not_found";$id;"known content";null) else empty end),
        ($selected[] as $c |
          if $c.game != $q.runtime.game then err("content_game";$c.id;$c.game;$q.runtime.game) else empty end,
          if accepts($c.compatibility.game_versions;$q.runtime.version)|not then err("game_version";$c.id;$c.compatibility.game_versions;$q.runtime.version) else empty end,
          if accepts($c.compatibility.editions;$q.runtime.edition)|not then err("edition";$c.id;$c.compatibility.editions;$q.runtime.edition) else empty end,
          if accepts($c.compatibility.loaders;$q.runtime.loader)|not then err("loader";$c.id;$c.compatibility.loaders;$q.runtime.loader) else empty end,
          if (($c.compatibility.loader_versions // [])|length)>0 and (([ $c.compatibility.loader_versions[] | version_ok($q.runtime.loader_version;.) ]|any)|not) then err("loader_version";$c.id;$c.compatibility.loader_versions;$q.runtime.loader_version) else empty end,
          if accepts($c.compatibility.os;$q.environment.os)|not then err("os";$c.id;$c.compatibility.os;$q.environment.os) else empty end,
          if accepts($c.compatibility.architectures;$q.environment.architecture)|not then err("architecture";$c.id;$c.compatibility.architectures;$q.environment.architecture) else empty end,
          if $c.compatibility.java != null and ($q.environment.java == null or $q.environment.java < $c.compatibility.java.min or $q.environment.java > $c.compatibility.java.max) then err("java";$c.id;$c.compatibility.java;$q.environment.java) else empty end,
          ($c.dependencies[]? as $d | select($d.required != false and ($available|index($d.id)) == null) | err("dependency_missing";$c.id;$d.id;null)),
          ($c.dependencies[]? as $d |
            ($defs|map(select(.id==$d.id))|first) as $depdef |
            select(($available|index($d.id)) != null and $d.version != null and ($depdef == null or (version_ok($depdef.version;$d.version)|not))) |
            err("dependency_version";$c.id;$d.version;($depdef.version // null))),
          ($c.conflicts[]? as $conflict |
            ($defs|map(select(.id==$conflict.id))|first) as $conflictdef |
            select(($available|index($conflict.id)) != null and ($conflict.version == null or ($conflictdef != null and version_ok($conflictdef.version;$conflict.version)))) |
            err("conflict";$c.id;($conflict.version // $conflict.id);($conflictdef.version // $conflict.id)))
        )
      ]) as $errors |
      {
        schema_version:2,
        kind:"CompatibilityResult",
        compatible:($errors|length == 0),
        decision:(if ($errors|length)==0 then "INSTALL_ALLOWED" else "INSTALL_BLOCKED" end),
        runtime:$q.runtime.id,
        content:$q.content,
        checks:{game:true,version:true,edition:true,loader:true,loader_version:true,java:true,os:true,architecture:true,dependencies:true,conflicts:true},
        errors:$errors
      }' | jq .
}

case "${1:-}" in
    check) [[ $# -eq 2 ]] || exit 2; compatibility_check "$2" ;;
    *) echo "Usage: compatibility_resolver.sh check REQUEST.json" >&2; exit 2 ;;
esac
