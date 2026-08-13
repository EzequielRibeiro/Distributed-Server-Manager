#!/bin/bash
# =============================================================
# update-manager.sh
#
# MÓDULO 11 - DSM UPDATE MANAGER
#
# Responsável por:
# - consultar novas versões no GitHub
# - baixar releases
# - validar pacote
# - chamar Módulo 10 INSTALL/RELEASE
#
# =============================================================

LOG_MODULE="update-manager"

# =============================================================
# Ambiente DSM
# =============================================================

if [ -z "$DSM_ROOT" ]; then
    DSM_ROOT="/opt/dsm"
fi

UPDATE_MANAGER_ROOT="$DSM_ROOT/update-manager"

# =============================================================
# Carrega núcleo DSM
# =============================================================

# shellcheck source=/dev/null
source "$DSM_ROOT/core/bootstrap.sh"

# =============================================================
# Configuração
# =============================================================

# shellcheck source=/dev/null
source "$UPDATE_MANAGER_ROOT/config.conf"

# =============================================================
# Clientes auxiliares
# =============================================================

# shellcheck source=/dev/null
source "$UPDATE_MANAGER_ROOT/github-client.sh"
# shellcheck source=/dev/null
source "$UPDATE_MANAGER_ROOT/download-release.sh"
# shellcheck source=/dev/null
source "$UPDATE_MANAGER_ROOT/verify-release.sh"

# =============================================================
# Verifica atualização disponível
# =============================================================

dsm_update_check()
{
    log_info "Consultando novas versões DSM"

    current_version=$(cat "$INSTALL_DIR/version" 2>/dev/null)

    if [ -z "$current_version" ]
    then
        log_error "Arquivo de versão não encontrado"

        notify_dispatch \
        "DSM Update" \
        "Instalação inválida"

        return 1
    fi

    release_json=$(github_latest_release)

    if [ -z "$release_json" ]
    then
        log_error "Falha consultando GitHub"
        return 1
    fi

    latest_version=$(github_release_version "$release_json")

    echo
    echo "Versão instalada:"
    echo "$current_version"

    echo
    echo "Última versão:"
    echo "$latest_version"

    if [ "$current_version" = "$latest_version" ]
    then
        echo
        echo "DSM já está atualizado."

        return 0
    fi

    echo
    echo "Nova versão disponível:"
    echo "$latest_version"

    return 10
}

# =============================================================
# Executa atualização
# =============================================================

dsm_update_run()
{
    log_info "Iniciando atualização DSM"

    dsm_update_check
    result=$?

    if [ "$result" -ne 0 ] && [ "$result" -ne 10 ]
    then
        return 1
    fi

    OLD_VERSION=$(cat "$INSTALL_DIR/version")

    release_json=$(github_latest_release)

    download_url=$(github_release_download "$release_json")

    if [ -z "$download_url" ]
    then
        log_error "Release sem pacote"

        notify_dispatch \
        "DSM Update" \
        "Pacote não encontrado"

        return 1
    fi

    echo
    echo "Baixando atualização..."

    package=$(download_release "$download_url")

    if [ ! -f "$package" ]
    then
        log_error "Falha no download"
        return 1
    fi

    # =========================================================
    # Obtém checksum SHA256
    # =========================================================

    echo
    echo "Obtendo checksum da release..."

    checksum=$(github_release_checksum "$release_json" || true)

    # =========================================================
    # Validação do pacote
    # =========================================================

    echo
    echo "Validando pacote..."

    if ! verify_release "$package" "$checksum"
    then
        log_error "Falha na validação do pacote DSM"

        notify_dispatch \
        "DSM Update" \
        "Pacote DSM inválido"

        events_emit \
        "DSM_UPDATE_FAILED" \
        "$latest_version" \
        2>/dev/null || true

        return 1
    fi

    # =========================================================
    # Extração temporária
    # =========================================================

    TEMP_DIR="/tmp/dsm-update"

    rm -rf "$TEMP_DIR"
    mkdir -p "$TEMP_DIR"

    tar -xzf \
    "$package" \
    -C "$TEMP_DIR"

    PACKAGE_ROOT=$(find "$TEMP_DIR" \
    -name version \
    -printf "%h\n" \
    | head -1)

    if [ -z "$PACKAGE_ROOT" ]
    then
        log_error "Estrutura DSM inválida"
        return 1
    fi

    echo
    echo "Pacote localizado:"
    echo "$PACKAGE_ROOT"

    # =========================================================
    # Executa Módulo 10
    # =========================================================

    echo
    echo "Executando atualização DSM..."

    "$DSM_ROOT/update.sh" \
    "$PACKAGE_ROOT"

    if [ $? -ne 0 ]
    then
        log_error "Módulo 10 falhou"

        notify_dispatch \
        "DSM Update" \
        "Atualização falhou"

        events_emit \
        "DSM_UPDATE_FAILED" \
        "$latest_version" \
        2>/dev/null || true

        return 1
    fi

    # =========================================================
    # Histórico e eventos
    # =========================================================

    dsm_update_history_add \
    "$OLD_VERSION" \
    "$latest_version"

    events_emit \
    "DSM_UPDATE_SUCCESS" \
    "$latest_version" \
    2>/dev/null || true

    echo
    echo "Atualização concluída com sucesso."
}

# =============================================================
# Histórico
# =============================================================

dsm_update_history()
{
    if [ -f "$HISTORY_FILE" ]
    then
        cat "$HISTORY_FILE"
    else
        echo "Nenhum histórico encontrado."
    fi
}

dsm_update_history_add()
{
    OLD="$1"
    NEW="$2"

    mkdir -p "$(dirname "$HISTORY_FILE")"

    echo "$(date '+%Y-%m-%d %H:%M:%S') - $OLD -> $NEW" \
    >> "$HISTORY_FILE"
}
