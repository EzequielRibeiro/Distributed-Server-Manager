#!/usr/bin/env bash
# =============================================================
# Capivara DSM - GitHub Releases Version Resolver v1
# =============================================================
set -Eeuo pipefail

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

vr_error(){ echo "[DSM][DISCOVERY][GITHUB][ERRO] $*" >&2; }

vr_headers()
{
    printf '%s\n' "Accept: application/vnd.github+json" "X-GitHub-Api-Version: 2022-11-28"
    [[ -n "${DSM_GITHUB_TOKEN:-}" ]] && printf '%s\n' "Authorization: Bearer ${DSM_GITHUB_TOKEN}"
}

vr_get()
{
    local URL="$1" ARGS=(--fail --silent --show-error --location --connect-timeout 10 --max-time 30) H
    while IFS= read -r H; do [[ -n "$H" ]] && ARGS+=(--header "$H"); done < <(vr_headers)
    curl "${ARGS[@]}" "$URL"
}

vr_normalize_release()
{
    jq -c \
      --arg repo "${VERSION_REPOSITORY}" \
      --arg variant "${VARIANT_ID}" \
      --arg asset_pattern "${VERSION_ASSET_PATTERN:-*}" \
      --arg game_version_asset_regex "${VERSION_GAME_VERSION_ASSET_REGEX:-}" '
      def glob_match($name; $pattern):
        if $pattern == "*" then true
        elif ($pattern | startswith("*") and endswith("*") and length > 2) then
          ($name | contains($pattern[1:-1]))
        elif ($pattern | startswith("*")) then
          ($name | endswith($pattern[1:]))
        elif ($pattern | endswith("*")) then
          ($name | startswith($pattern[0:-1]))
        else
          $name == $pattern
        end;

      def text:
        ((.name // "") + " " + (.tag_name // "") + " " + (.body // "") + " " +
         ([.assets[]?.name] | join(" ")));

      def generic_game_versions:
        text as $t |
        [$t | scan("1\\.[0-9]{1,2}(?:\\.[0-9]{1,2})?")] |
        unique |
        sort_by(split(".") | map(tonumber? // 0));

      def asset_game_versions:
        if $game_version_asset_regex == "" then []
        else
          [.assets[]?.name |
            try capture($game_version_asset_regex).version catch empty] |
          map(select(. != null and . != "")) |
          unique |
          sort_by(split(".") | map(tonumber? // 0))
        end;

      def game_versions:
        asset_game_versions as $a |
        if ($a|length) > 0 then $a else generic_game_versions end;

      def loaders:
        (text | ascii_downcase) as $t |
        [if ($t|contains("forge")) then "forge" else empty end,
         if ($t|contains("neoforge")) then "neoforge" else empty end,
         if ($t|contains("fabric")) then "fabric" else empty end] |
        unique;

      {
        repository:$repo,
        variant:$variant,
        tag:.tag_name,
        name:(.name // .tag_name),
        prerelease:(.prerelease // false),
        draft:(.draft // false),
        published_at:.published_at,
        minecraft_versions:game_versions,
        loaders:loaders,
        assets:[
          .assets[]? |
          select(glob_match(.name; $asset_pattern)) |
          select((.name | ascii_downcase | contains("sources")) | not) |
          select((.name | ascii_downcase | contains("javadoc")) | not) |
          {
            name:.name,
            size:.size,
            url:.browser_download_url,
            content_type:.content_type
          }
        ]
      }'
}

vr_list()
{
    [[ -n "${VERSION_REPOSITORY:-}" ]] || { vr_error "VERSION_REPOSITORY não definido."; return 1; }
    command -v curl >/dev/null || { vr_error "curl não disponível."; return 1; }
    command -v jq >/dev/null || { vr_error "jq não disponível."; return 1; }

    local LIMIT="${VERSION_DISCOVERY_LIMIT:-50}"
    local URL="https://api.github.com/repos/${VERSION_REPOSITORY}/releases?per_page=${LIMIT}"
    local RAW
    RAW="$(vr_get "$URL")" || return 1

    jq -c '.[] | select(.draft != true)' <<<"$RAW" |
      while IFS= read -r RELEASE; do
        vr_normalize_release <<<"$RELEASE"
      done |
      jq -s --arg game "${GAME_ID:-unknown}" --arg variant "${VARIANT_ID:-unknown}" '
        {game:$game,variant:$variant,source:"github-releases",versions:.}'
}

vr_resolve()
{
    local SELECTOR="$1"
    local LIST
    LIST="$(vr_list)" || return 1

    jq -c --arg s "$SELECTOR" '
      .versions as $v |
      (if $s=="latest" or $s=="current"
       then ($v | first)
       else ($v |
         map(select(.tag==$s or .name==$s or (.minecraft_versions|index($s)))) |
         first)
       end) as $r |
      if $r == null then
        {error:"version_not_found",selector:$s}
      elif (($r.assets // []) | length) == 0 then
        {error:"asset_not_found",selector:$s,tag:$r.tag,repository:$r.repository}
      else
        ($r.assets | first) as $asset |
        $r + {
          selected_asset:$asset,
          provider:"github",
          install:{repository:$r.repository,tag:$r.tag,asset:$asset.name}
        }
      end' <<<"$LIST"
}

version_resolver_execute()
{
    local ACTION="$1" GAME="$2" VARIANT="$3" SELECTOR="${4:-}"
    case "$ACTION" in
      list) vr_list ;;
      resolve) vr_resolve "$SELECTOR" ;;
      *) vr_error "Ação desconhecida: $ACTION"; return 2 ;;
    esac
}

export -f version_resolver_execute
