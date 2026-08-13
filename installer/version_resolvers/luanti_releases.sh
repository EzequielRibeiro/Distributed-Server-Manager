#!/usr/bin/env bash
# =============================================================
# Capivara DSM
# Luanti Release Resolver v2
#
# Source of truth:
#   GitHub API - luanti-org/luanti releases
#
# O resolver somente descobre e seleciona versões.
# A compilação pertence ao provider source-build.
# =============================================================

set -Eeuo pipefail

LUANTI_REPOSITORY="${LUANTI_REPOSITORY:-luanti-org/luanti}"
LUANTI_API="${LUANTI_API:-https://api.github.com/repos/${LUANTI_REPOSITORY}/releases}"

luanti_error()
{
    echo "[DSM][DISCOVERY][LUANTI][ERRO] $*" >&2
}

luanti_requirements()
{
    command -v curl >/dev/null 2>&1 || {
        luanti_error "curl não disponível."
        return 1
    }

    command -v jq >/dev/null 2>&1 || {
        luanti_error "jq não disponível."
        return 1
    }
}

luanti_fetch_releases()
{
    luanti_requirements || return 1

    curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --connect-timeout 15 \
        --max-time 60 \
        --retry 2 \
        --retry-delay 1 \
        --header "Accept: application/vnd.github+json" \
        --header "X-GitHub-Api-Version: 2022-11-28" \
        --user-agent "Capivara-DSM/1.0 LuantiResolver" \
        "${LUANTI_API}?per_page=30"
}

luanti_list()
{
    local RAW

    RAW="$(luanti_fetch_releases)" || return 1

    if ! jq -e 'type == "array"' >/dev/null 2>&1 <<<"${RAW}"
    then
        luanti_error "Resposta inesperada da API GitHub."
        return 1
    fi

    jq -c \
        --arg repository "${LUANTI_REPOSITORY}" '
        {
            game: "luanti",
            variant: "stable",
            source: "github-official-repository",
            versions: [
                .[]
                | select(.draft == false)
                | select(.prerelease == false)
                | select(
                    (.tag_name | type == "string")
                    and
                    (.tag_name | length > 0)
                )
                | {
                    version: (
                        .tag_name
                        | sub("^v"; "")
                    ),
                    build: .tag_name,
                    tag: .tag_name,
                    channel: "stable",
                    provider: "source-build",
                    repository: $repository,
                    install: {
                        repository: $repository
                    }
                }
            ]
        }
    ' <<<"${RAW}"
}

luanti_resolve()
{
    local SELECTOR="${1:-latest}"
    local LIST

    LIST="$(luanti_list)" || return 1

    jq -c \
        --arg selector "${SELECTOR}" '
        .versions as $versions |

        (
            if (
                $selector == "latest"
                or $selector == "stable"
                or $selector == "current"
            )
            then
                ($versions | first)
            else
                (
                    $versions
                    | map(
                        select(
                            .version == $selector
                            or .tag == $selector
                            or .build == $selector
                        )
                    )
                    | first
                )
            end
        ) as $result |

        if $result == null
        then
            {
                error: "version_not_found",
                selector: $selector
            }
        else
            $result
        end
    ' <<<"${LIST}"
}

version_resolver_execute()
{
    local ACTION="${1:-}"
    local GAME="${2:-}"
    local VARIANT="${3:-}"
    local SELECTOR="${4:-}"

    case "${ACTION}" in
        list)
            luanti_list
            ;;

        resolve)
            luanti_resolve "${SELECTOR:-latest}"
            ;;

        *)
            luanti_error "Ação desconhecida: ${ACTION}"
            return 2
            ;;
    esac
}

export -f version_resolver_execute
