#!/usr/bin/env bash
# =============================================================
# Capivara DSM - Minecraft Bedrock Dedicated Server Resolver v2
#
# Source of truth:
# Minecraft/Microsoft official download API
#
# Endpoint:
# https://net-secondary.web.minecraft-services.net/api/v1.0/download/links
#
# No HTML scraping.
# =============================================================

set -Eeuo pipefail

BEDROCK_API_BASE="${BEDROCK_API_BASE:-https://net-secondary.web.minecraft-services.net}"
BEDROCK_LINKS_ENDPOINT="${BEDROCK_LINKS_ENDPOINT:-/api/v1.0/download/links}"

bedrock_error() {
    echo "[DSM][DISCOVERY][BEDROCK][ERRO] $*" >&2
}

bedrock_requirements() {
    command -v curl >/dev/null 2>&1 || {
        bedrock_error "curl não disponível."
        return 1
    }

    command -v jq >/dev/null 2>&1 || {
        bedrock_error "jq não disponível."
        return 1
    }
}

bedrock_fetch_links() {
    bedrock_requirements || return 1

    curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --connect-timeout 15 \
        --max-time 60 \
        --retry 2 \
        --retry-delay 1 \
        --header "Accept: application/json" \
        --user-agent "Capivara-DSM/1.0 MinecraftBedrockResolver" \
        "${BEDROCK_API_BASE}${BEDROCK_LINKS_ENDPOINT}"
}

bedrock_extract_version() {
    local URL="${1:-}"

    basename "${URL}" |
        sed -E 's/^bedrock-server-//; s/\.zip$//'
}

bedrock_list() {
    local RAW
    RAW="$(bedrock_fetch_links)" || return 1

    if ! jq -e '.result.links | type == "array"' >/dev/null 2>&1 <<<"${RAW}"
    then
        bedrock_error "Resposta inesperada da API oficial."
        return 1
    fi

    local URL

    URL="$(
        jq -r '
            .result.links[]
            | select(.downloadType == "serverBedrockLinux")
            | .downloadUrl
        ' <<<"${RAW}" |
        head -n1
    )"

    if [[ -z "${URL}" || "${URL}" == "null" ]]
    then
        bedrock_error "A API não retornou serverBedrockLinux."
        return 1
    fi

    local VERSION FILE
    VERSION="$(bedrock_extract_version "${URL}")"
    FILE="$(basename "${URL}")"

    jq -nc \
        --arg version "${VERSION}" \
        --arg file "${FILE}" \
        --arg url "${URL}" '
        {
            game: "minecraft",
            variant: "bedrock",
            source: "minecraft-official-api",
            versions: [
                {
                    version: $version,
                    minecraft_versions: [$version],
                    build: $version,
                    channel: "live",
                    platform: "linux-x86_64",
                    provider: "http-archive",
                    executable: "bedrock_server",
                    archive: {
                        type: "zip",
                        executable: "bedrock_server"
                    },
                    request: {
                        referer: "https://www.minecraft.net/en-us/download/server/bedrock"
                    },
                    selected_asset: {
                        name: $file,
                        url: $url,
                        content_type: "application/zip"
                    },
                    install: {
                        url: $url,
                        asset: $file,
                        archive_type: "zip",
                        executable: "bedrock_server"
                    }
                }
            ]
        }'
}

bedrock_resolve() {
    local SELECTOR="${1:-latest}"
    local LIST

    LIST="$(bedrock_list)" || return 1

    jq -c \
        --arg selector "${SELECTOR}" '
        .versions as $versions |

        (
            if (
                $selector == "latest"
                or $selector == "live"
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

version_resolver_execute() {
    local ACTION="${1:-}"
    local GAME="${2:-}"
    local VARIANT="${3:-}"
    local SELECTOR="${4:-}"

    case "${ACTION}" in
        list)
            bedrock_list
            ;;

        resolve)
            bedrock_resolve "${SELECTOR:-latest}"
            ;;

        *)
            bedrock_error "Ação desconhecida: ${ACTION}"
            return 2
            ;;
    esac
}

export -f version_resolver_execute
