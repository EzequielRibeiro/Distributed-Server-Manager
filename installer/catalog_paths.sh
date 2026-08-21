#!/usr/bin/env bash
# Capivara DSM - catalog path resolution compatibility layer
# Canonical layout wins over the legacy layout when the same definition ID exists.

catalog_runtime_canonical_root()
{
    printf '%s\n' "${CATALOG_ROOT}/games"
}

catalog_runtime_legacy_root()
{
    printf '%s\n' "${CATALOG_ROOT}/runtimes"
}

catalog_runtime_definition_files()
{
    local CANONICAL_ROOT LEGACY_ROOT
    CANONICAL_ROOT="$(catalog_runtime_canonical_root)"
    LEGACY_ROOT="$(catalog_runtime_legacy_root)"

    # Canonical files are emitted first. Consumers that de-duplicate by ID
    # therefore preserve the new namespace when both layouts coexist.
    if [[ -d "${CANONICAL_ROOT}" ]]
    then
        find "${CANONICAL_ROOT}" \
            -mindepth 3 -maxdepth 3 \
            -type f -path '*/runtimes/*.json' \
            -print0 2>/dev/null
    fi

    if [[ -d "${LEGACY_ROOT}" ]]
    then
        find "${LEGACY_ROOT}" \
            -type f -name '*.json' \
            -print0 2>/dev/null
    fi
}

catalog_runtime_find()
{
    local ID="$1" FILE

    while IFS= read -r -d '' FILE
    do
        if jq -e --arg id "${ID}" '.id == $id' "${FILE}" >/dev/null
        then
            printf '%s\n' "${FILE}"
            return 0
        fi
    done < <(catalog_runtime_definition_files)

    return 1
}

catalog_runtime_list()
{
    local GAME="${1:-}"

    # The stream is canonical-first. reduce() keeps the first definition for
    # each ID, making canonical manifests authoritative during migration while
    # still exposing legacy-only definitions.
    catalog_runtime_definition_files |
        xargs -0 -r jq -c 'select(.schema_version == 2)' |
        jq -sc --arg game "${GAME}" '
          reduce .[] as $item
            ({}; if has($item.id) then . else . + {($item.id): $item} end) |
          [.[]] |
          map(select($game == "" or .game == $game)) |
          sort_by(.game, .edition // "", .variant // "", .id)'
}
