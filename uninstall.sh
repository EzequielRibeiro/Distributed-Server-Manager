#!/usr/bin/env bash
#==============================================================================
# DayZ Server Manager (DSM)
# uninstall.sh
# Desinstalador Oficial | Official Uninstaller
# Versão | Version : 3.0.0
# Recursos | Features
#  • Remoção segura do DSM | Safe removal of DSM
#  • Backup final opcional | Optional final backup
#  • Remoção Systemd | Systemd removal
#  • Preserva servidor DayZ/LinuxGSM | Preserves DayZ/LinuxGSM server
#  • Limpeza do comando global dsm | Global dsm command cleanup
#==============================================================================

set -Eeuo pipefail

#############################################
# Informações | Information
#############################################
readonly DSM_NAME="DayZ Server Manager"
DSM_VERSION="1.0.0"
INSTALL_DIR="/opt/dsm"
BACKUP_DIR="/opt/dsm-backup"
BIN_LINK="/usr/local/bin/dsm"
readonly SYSTEMD_DIR="/etc/systemd/system"
CONFIG_FILE="${INSTALL_DIR}/config/dsm.conf"

#############################################
# Cores | Colors
#############################################
RED="\033[31m"
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[36m"
RESET="\033[0m"

#############################################
# Logger
#############################################
log_info() {
    printf "${BLUE}[*]${RESET} %s\n" "$1"
}

log_success() {
    printf "${GREEN}[OK]${RESET} %s\n" "$1"
}

log_warning() {
    printf "${YELLOW}[WARN]${RESET} %s\n" "$1"
}

log_error() {
    printf "${RED}[ERRO]${RESET} %s\n" "$1"
}

#############################################
# Root
#############################################
require_root() {
    if [[ "$EUID" -ne 0 ]]
    then
        log_error "Execute utilizando sudo."
        log_error "Run using sudo."
        exit 1
    fi
}

#############################################
# Proteção | Protection
#############################################
validate_install_path() {
    if [[ "${INSTALL_DIR}" != "/opt/dsm" ]]
    then
        log_error "Caminho de instalação inválido."
        log_error "Invalid installation path."
        exit 1
    fi
}

#############################################
# Carrega Configuração DSM | Load DSM Configuration
#############################################
load_config() {
    DSM_USER=""
    if [[ -f "${CONFIG_FILE}" ]]
    then
        source "${CONFIG_FILE}"
        log_info "Configuração DSM carregada."
        log_info "DSM configuration loaded."
    else
        log_warning "Arquivo dsm.conf não encontrado."
        log_warning "dsm.conf file not found."
    fi
}

#############################################
# Backup Final
#############################################
final_backup() {
    echo
    read -rp "Criar backup final antes da remoção? (s/N) | Create final backup before removal? (y/N): " ANSWER
    if [[ "${ANSWER}" == "s" || "${ANSWER}" == "S" || "${ANSWER}" == "y" || "${ANSWER}" == "Y" ]]
    then
        if [[ -x "${BIN_LINK}" ]]
        then
            log_info "Executando backup final..."
            log_info "Executing final backup..."
            "${BIN_LINK}" backup create || log_warning "Falha ao executar backup | Failed to execute backup."
        else
            log_warning "Comando dsm indisponível | dsm command unavailable."
        fi
    fi
}

#############################################
# Remove Serviços Systemd | Remove Systemd Services
#############################################
remove_systemd_services() {
    log_info "Removendo serviços Systemd..."
    log_info "Removing Systemd services..."
    SERVICES=(
        "dsm-monitor.service"
        "dsm-dashboard.service"
        "dsm-backup.service"
        "dsm-backup.timer"
    )

    for SERVICE in "${SERVICES[@]}"
    do
        systemctl disable --now "${SERVICE}" 2>/dev/null || true
        rm -f "${SYSTEMD_DIR}/${SERVICE}"
    done
    systemctl daemon-reload
    log_success "Serviços removidos | Services removed."
}

#############################################
# Remove comando DSM | Remove DSM command
#############################################
remove_command() {
    if [[ -L "${BIN_LINK}" || -f "${BIN_LINK}" ]]
    then
        rm -f "${BIN_LINK}"
        log_success "Comando dsm removido | dsm command removed."
    fi
}

#############################################
# Remove arquivos DSM | Remove DSM files
#############################################
remove_installation() {
    if [[ -d "${INSTALL_DIR}" ]]
    then
        log_info "Removendo arquivos DSM..."
        log_info "Removing DSM files..."
        rm -rf "${INSTALL_DIR}"
        log_success "Diretório DSM removido | DSM directory removed."
    else
        log_warning "Instalação DSM não encontrada | DSM installation not found."
    fi
}

#############################################
# Backup externo | External backup
#############################################
remove_external_backup() {
    if [[ ! -d "${BACKUP_DIR}" ]]
    then
        return
    fi
    echo
    read -rp "Remover também ${BACKUP_DIR}? (s/N) | Remove ${BACKUP_DIR} as well? (y/N): " ANSWER
    if [[ "${ANSWER}" == "s" || "${ANSWER}" == "S" || "${ANSWER}" == "y" || "${ANSWER}" == "Y" ]]
    then
        rm -rf "${BACKUP_DIR}"
        log_success "Backup externo removido | External backup removed."
    else
        log_info "Backup externo preservado | External backup preserved."
    fi
}

#############################################
# Confirmação | Confirmation
#############################################
confirm_remove() {
    echo
    echo "============================================================"
    echo " Remover | Remove ${DSM_NAME}"
    echo "============================================================"
    echo
    echo "Será removido: | Will be removed:"
    echo
    echo " - ${INSTALL_DIR}"
    echo " - Serviços Systemd DSM | DSM Systemd Services"
    echo " - Comando | Command ${BIN_LINK}"
    echo
    echo "Será preservado: | Will be preserved:"
    echo
    echo " - LinuxGSM"
    echo " - Servidor DayZ | DayZ Server"
    echo " - Mods"
    echo " - Serverfiles"
    echo
    read -rp "Continuar? (s/N) | Continue? (y/N): " ANSWER
    if [[ "${ANSWER}" != "s" && "${ANSWER}" != "S" && "${ANSWER}" != "y" && "${ANSWER}" != "Y" ]]
    then
        echo "Cancelado | Cancelled."
        exit 0
    fi
}

#############################################
# Main
#############################################
main() {
    require_root
    validate_install_path
    confirm_remove
    load_config
    final_backup
    remove_systemd_services
    remove_command
    remove_installation
    remove_external_backup
    echo
    echo "============================================================"
    log_success "DSM removido com sucesso | DSM removed successfully."
    echo "============================================================"
    echo
}

main "$@"
