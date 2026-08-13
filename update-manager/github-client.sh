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
        log_error "GITHUB_API não configurado"
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
        log_error "Falha consultando GitHub"
        return 1
    fi

    echo "$response"
}

# =============================================================
# Obtém versão da release
# =============================================================

github_release_version()
{
    release_json="$1"

    echo "$release_json" |
    jq -r '.tag_name'
}

# =============================================================
# Obtém URL do pacote DSM
#
# Prioridade:
#
# 1 DSM-*-release.tar.gz
# 2 DSM-*.tar.gz
#
# =============================================================

github_release_download()
{
    release_json="$1"

    asset_url=$(echo "$release_json" |
    jq -r '
    .assets[]
    .browser_download_url
    ' |
    grep "DSM-" |
    grep "release.tar.gz" |
    head -1)

    if [ -z "$asset_url" ]
    then
        asset_url=$(echo "$release_json" |
        jq -r '
        .assets[]
        .browser_download_url
        ' |
        grep "DSM-" |
        grep "\.tar\.gz" |
        head -1)
    fi

    if [ -z "$asset_url" ]
    then
        log_error \
        "Nenhum pacote DSM encontrado na Release"

        return 1
    fi

    echo "$asset_url"
}

# =============================================================
# Verifica se release pertence ao canal
# =============================================================

github_release_channel()
{
    release_json="$1"

    case "$UPDATE_CHANNEL" in
    stable)
        echo "$release_json" |
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
        log_error "Canal inválido: $UPDATE_CHANNEL"
        return 1
        ;;
    esac
}
