#!/bin/bash
# =============================================================
# github-client.sh
#
# MÓDULO 11 - Cliente GitHub DSM
#
# Responsável por:
# - consultar GitHub Releases
# - obter versão
# - localizar pacote DSM oficial
#
# Funções usadas por command substitution devem manter stdout
# reservado ao valor retornado. Mensagens de erro vão para stderr.
#
# =============================================================

# =============================================================
# Carrega configuração
# =============================================================

source "$DSM_ROOT/update-manager/config.conf"

# =============================================================
# Consulta última release
# =============================================================

github_latest_release()
{
    if [ -z "$GITHUB_API" ]
    then
        log_error "GITHUB_API não configurado" >&2
        return 1
    fi

    response=$(curl \
        --silent \
        --show-error \
        --fail \
        --connect-timeout "$GITHUB_TIMEOUT" \
        "$GITHUB_API"
    )

    if [ $? -ne 0 ]
    then
        log_error "Falha consultando GitHub" >&2
        return 1
    fi

    printf '%s\n' "$response"
}

# =============================================================
# Obtém versão da release
# =============================================================

github_release_version()
{
    release_json="$1"

    printf '%s\n' "$release_json" |
    jq -r '.tag_name'
}

# =============================================================
# Obtém URL do pacote oficial Capivara DSM
#
# Contrato:
# tag vX.Y.Z
# asset capivara-dsm-X.Y.Z.tar.gz
#
# =============================================================

github_release_download()
{
    local release_json="$1"
    local release_version
    local asset_name
    local asset_url

    release_version=$(github_release_version "$release_json")

    if [ -z "$release_version" ] || [ "$release_version" = "null" ]
    then
        log_error "Release sem tag_name válido." >&2
        return 1
    fi

    release_version="${release_version#v}"
    asset_name="capivara-dsm-${release_version}.tar.gz"

    asset_url=$(printf '%s\n' "$release_json" |
        jq -r --arg asset_name "$asset_name" '
            .assets[]?
            | select(.name == $asset_name)
            | .browser_download_url
        ' |
        head -1)

    if [ -z "$asset_url" ] || [ "$asset_url" = "null" ]
    then
        log_error \
            "Pacote oficial não encontrado na release: ${asset_name}" >&2
        return 1
    fi

    printf '%s\n' "$asset_url"
}

# =============================================================
# Obtém URL do checksum SHA256 oficial
#
# Contrato:
# tag vX.Y.Z
# asset capivara-dsm-X.Y.Z.tar.gz.sha256
#
# =============================================================

github_release_checksum_download()
{
    local release_json="$1"
    local release_version
    local asset_name
    local asset_url

    release_version=$(github_release_version "$release_json")

    if [ -z "$release_version" ] || [ "$release_version" = "null" ]
    then
        log_error "Release sem tag_name válido." >&2
        return 1
    fi

    release_version="${release_version#v}"
    asset_name="capivara-dsm-${release_version}.tar.gz.sha256"

    asset_url=$(printf '%s\n' "$release_json" |
        jq -r --arg asset_name "$asset_name" '
            .assets[]?
            | select(.name == $asset_name)
            | .browser_download_url
        ' |
        head -1)

    if [ -z "$asset_url" ] || [ "$asset_url" = "null" ]
    then
        log_error \
            "Checksum oficial não encontrado na release: ${asset_name}" >&2
        return 1
    fi

    printf '%s\n' "$asset_url"
}

# =============================================================
# Verifica se release pertence ao canal
# =============================================================

github_release_channel()
{
    release_json="$1"

    case "$UPDATE_CHANNEL" in
    stable)
        printf '%s\n' "$release_json" |
        jq -r '.prerelease' |
        grep -q false
        ;;
    beta)
        return 0
        ;;
    dev)
        return 0
        ;;
    *)
        log_error "Canal inválido: $UPDATE_CHANNEL" >&2
        return 1
        ;;
    esac
}
