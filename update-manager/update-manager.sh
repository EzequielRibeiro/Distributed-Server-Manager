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

# Instalações atualizadas a partir de versões antigas podem manter o marcador
# do bootstrap no ambiente mesmo quando logger/semver ainda não foram
# carregados. Recarregue apenas as dependências ausentes para que o próprio
# Update Manager consiga reparar esse estado.
if ! declare -F log_info >/dev/null 2>&1 || ! declare -F log_error >/dev/null 2>&1
then
    if [ -f "$DSM_ROOT/core/logger.sh" ]
    then
        # shellcheck source=/dev/null
        source "$DSM_ROOT/core/logger.sh"
    fi
fi

if ! declare -F is_semver >/dev/null 2>&1 || ! declare -F semver_compare >/dev/null 2>&1
then
    if [ -f "$DSM_ROOT/core/semver.sh" ]
    then
        # shellcheck source=/dev/null
        source "$DSM_ROOT/core/semver.sh"
    fi
fi

declare -F log_info >/dev/null 2>&1 || log_info() { printf '%s\n' "$*"; }
declare -F log_error >/dev/null 2>&1 || log_error() { printf 'Erro: %s\n' "$*" >&2; }

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
# Notificação tolerante a backend ausente
# =============================================================

dsm_update_notify()
{
    if declare -F notify_dispatch >/dev/null 2>&1
    then
        notify_dispatch "$@"
        return 0
    fi

    if declare -F log_info >/dev/null 2>&1
    then
        log_info "Notificação indisponível: $*"
    else
        printf '%s\n' "Notificação indisponível: $*"
    fi

    return 0
}

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

        dsm_update_notify \
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

    if [ -z "$latest_version" ] || [ "$latest_version" = "null" ]
    then
        log_error "Release sem versão válida"
        return 1
    fi

    # GitHub usa tags vX.Y.Z; o arquivo version usa X.Y.Z.
       latest_version="${latest_version#v}"

    if ! is_semver "$current_version"
    then
        log_error "Versão instalada inválida: $current_version"
        return 1
    fi

    if ! is_semver "$latest_version"
    then
        log_error "Versão remota inválida: $latest_version"
        return 1
    fi

    echo
    echo "Versão instalada:"
    echo "$current_version"

    echo
    echo "Última versão:"
    echo "$latest_version"

    comparison=$(semver_compare "$latest_version" "$current_version")

    case "$comparison" in
        0)
            echo
            echo "DSM já está atualizado."
            return 0
            ;;

        1)
            echo
            echo "Nova versão disponível:"
            echo "$latest_version"
            return 10
            ;;

        -1)
            echo
            echo "A versão instalada está à frente da release disponível."
            return 0
            ;;

        *)
            log_error "Falha comparando versões DSM"
            return 1
            ;;
    esac
}

# Extract each verified release into a private, unique workspace. A legacy
# fixed path /tmp/dsm-update was shared across executions and could delete
# another updater's files. The subshell owns its EXIT cleanup exclusively and
# cannot override traps installed by the calling Controller/CLI.
dsm_update_execute_target()
(
    set -Eeuo pipefail
    local package="$1"
    local expected_version="$2"
    local workspace package_root target_updater installed_version

    workspace="$(mktemp -d "${TMPDIR:-/tmp}/dsm-update.XXXXXXXX")" || {
        log_error "Não foi possível criar diretório de atualização isolado"
        return 1
    }
    chmod 0700 "$workspace"
    trap 'rm -rf -- "$workspace"' EXIT

    if ! tar -xzf "$package" -C "$workspace"; then
        log_error "Falha ao extrair pacote DSM"
        return 1
    fi

    package_root="$(find "$workspace" -mindepth 2 -maxdepth 3 -type f -name version -printf '%h\n' | head -1)"
    if [[ -z "$package_root" || ! -f "$package_root/update.sh" ]]; then
        log_error "Estrutura DSM inválida ou updater ausente"
        return 1
    fi

    target_updater="$package_root/update.sh"
    echo
    echo "Pacote localizado: $package_root"
    echo "Executando atualização DSM com o updater da versão alvo..."

    if ! /bin/bash "$target_updater" "$package_root"; then
        log_error "Módulo 10 da versão alvo falhou"
        return 1
    fi

    installed_version="$(cat "$INSTALL_DIR/version" 2>/dev/null || true)"
    if [[ "$installed_version" != "$expected_version" ]]; then
        log_error "Updater alvo terminou sem instalar a versão esperada: esperado=$expected_version instalado=${installed_version:-unknown}"
        return 1
    fi
)

# =============================================================
# Executa atualização
# =============================================================

dsm_update_run()
{
    local result
    local target_updater

    log_info "Iniciando atualização DSM"

    if dsm_update_check
    then
        result=0
    else
        result=$?
    fi

    case "$result" in
        0)
            # A instalação já está na versão selecionada pelo canal.
            # Não deve baixar nem reinstalar a mesma release.
            return 0
            ;;

        10)
            # Atualização disponível. Continua o pipeline.
            ;;

        *)
            log_error "Falha verificando atualização DSM"
            return 1
            ;;
    esac

    OLD_VERSION=$(cat "$INSTALL_DIR/version")

    release_json=$(github_latest_release)

    download_url=$(github_release_download "$release_json")

    if [ -z "$download_url" ]
    then
        log_error "Release sem pacote"

        dsm_update_notify \
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
    # Obtém checksum SHA256 oficial
    # =========================================================

    echo
    echo "Obtendo checksum da release..."

    checksum_url=$(github_release_checksum_download "$release_json")

    if [ -z "$checksum_url" ]
    then
        log_error "Release sem checksum SHA256 oficial"

        dsm_update_notify \
            "DSM Update" \
            "Checksum SHA256 não encontrado"

        return 1
    fi

    checksum_file=$(download_checksum "$checksum_url")

    if [ ! -f "$checksum_file" ]
    then
        log_error "Falha no download do checksum SHA256"

        dsm_update_notify \
            "DSM Update" \
            "Falha no download do checksum SHA256"

        return 1
    fi

    checksum=$(awk 'NR == 1 { print $1 }' "$checksum_file")

    if ! printf '%s\n' "$checksum" |
        grep -Eq '^[[:xdigit:]]{64}$'
    then
        log_error "Checksum SHA256 oficial inválido"

        dsm_update_notify \
            "DSM Update" \
            "Checksum SHA256 oficial inválido"

        return 1
    fi

    # =========================================================
    # Validação do pacote
    # =========================================================

    echo
    echo "Validando pacote..."

    if ! verify_release "$package" "$checksum"
    then
        log_error "Falha na validação do pacote DSM"

        dsm_update_notify \
        "DSM Update" \
        "Pacote DSM inválido"

        events_emit \
        "DSM_UPDATE_FAILED" \
        "$latest_version" \
        2>/dev/null || true

        return 1
    fi

    # The target runs inside a private handoff directory which is removed
    # on every ordinary exit (success, validation failure or updater error).
    # Existing /tmp/dsm-update is never touched.
    if ! dsm_update_execute_target "$package" "$latest_version"; then
        dsm_update_notify "DSM Update" "Atualização não concluída"
        events_emit "DSM_UPDATE_FAILED" "$latest_version" 2>/dev/null || true
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
    chmod 0644 "$HISTORY_FILE"
}
