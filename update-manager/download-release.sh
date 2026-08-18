#!/bin/bash
# =============================================================
# download-release.sh
#
# MÓDULO 11 - DSM Update Manager
#
# Responsável por:
# - baixar release DSM
# - armazenar cache
# - validar download
# - controlar versões antigas
#
# Contrato das funções de download:
# - stdout: somente o caminho do arquivo retornado
# - stderr: mensagens informativas e de progresso
#
# Esse contrato é necessário porque o Update Manager usa
# command substitution, por exemplo:
#   package=$(download_release "$download_url")
#
# =============================================================

source "$DSM_ROOT/update-manager/config.conf"

download_release()
{
    local URL="$1"

    if [ -z "$URL" ]
    then
        log_error \
        "URL da release não informada."
        return 1
    fi

    mkdir -p "$DOWNLOAD_DIR"

    # =========================================================
    # Nome do arquivo
    # =========================================================

    local FILENAME

    FILENAME=$(basename "$URL")

    if [ -z "$FILENAME" ]
    then
        FILENAME="DSM-update.tar.gz"
    fi

    local FILE="$DOWNLOAD_DIR/$FILENAME"

    # =========================================================
    # Evita novo download
    # =========================================================

    if [ -f "$FILE" ]
    then
        printf '%s\n' "$FILE"
        return 0
    fi

    printf '\n' >&2
    printf 'Baixando release DSM:\n' >&2
    printf '%s\n' "$URL" >&2
    printf '\n' >&2

    if ! curl \
        --fail \
        --location \
        --connect-timeout "$DOWNLOAD_TIMEOUT" \
        --output "$FILE" \
        "$URL"
    then
        log_error \
        "Erro no download."
        rm -f "$FILE"
        return 1
    fi

    # =========================================================
    # Validação básica do arquivo
    # =========================================================

    if ! tar -tzf "$FILE" >/dev/null 2>&1
    then
        log_error \
        "Pacote baixado inválido."
        rm -f "$FILE"
        return 1
    fi

    printf '%s\n' "$FILE"
}

# =============================================================
# Limpeza de releases antigas
# =============================================================

cleanup_downloads()
{
    if [ "$AUTO_CLEANUP_CACHE" != "1" ]
    then
        return 0
    fi

    cd "$DOWNLOAD_DIR" || return 0

    COUNT=$(ls -1 *.tar.gz 2>/dev/null | wc -l)

    if [ "$COUNT" -le "$KEEP_RELEASES" ]
    then
        return 0
    fi

    REMOVE=$((COUNT-KEEP_RELEASES))

    ls -1t *.tar.gz |
    tail -n "$REMOVE" |
    xargs -r rm -f
}

# =============================================================
# Download do checksum SHA256 oficial
# =============================================================

download_checksum()
{
    local URL="$1"
    local FILENAME
    local FILE

    if [ -z "$URL" ]
    then
        log_error \
            "URL do checksum não informada."
        return 1
    fi

    mkdir -p "$CHECKSUM_DIR"

    FILENAME=$(basename "$URL")

    if [ -z "$FILENAME" ]
    then
        log_error \
            "Nome do arquivo de checksum inválido."
        return 1
    fi

    FILE="$CHECKSUM_DIR/$FILENAME"

    if [ -f "$FILE" ]
    then
        printf '%s\n' "$FILE"
        return 0
    fi

    printf '\n' >&2
    printf 'Baixando checksum SHA256:\n' >&2
    printf '%s\n' "$URL" >&2
    printf '\n' >&2

    if ! curl \
        --fail \
        --location \
        --connect-timeout "$DOWNLOAD_TIMEOUT" \
        --output "$FILE" \
        "$URL"
    then
        log_error \
            "Erro no download do checksum."
        rm -f "$FILE"
        return 1
    fi

    if [ ! -s "$FILE" ]
    then
        log_error \
            "Arquivo de checksum vazio."
        rm -f "$FILE"
        return 1
    fi

    printf '%s\n' "$FILE"
}
