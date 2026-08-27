#!/usr/bin/env bash
# Capivara Distributed Server Manager - desinstalador oficial
# Dados externos, servidores de jogos, mods e backups são preservados por padrão.
set -Eeuo pipefail

readonly DSM_NAME="Capivara Distributed Server Manager"
INSTALL_DIR="${INSTALL_DIR:-/opt/dsm}"
BACKUP_DIR="${BACKUP_DIR:-/opt/dsm-backup}"
DSM_LINK="${DSM_LINK:-/usr/local/bin/dsm}"
CAP_LINK="${CAP_LINK:-/usr/local/bin/cap}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
CONFIG_FILE="${CONFIG_FILE:-${INSTALL_DIR}/config/dsm.conf}"
DSM_USER=""; DSM_GROUP=""
RED="\033[31m"; GREEN="\033[32m"; YELLOW="\033[33m"; BLUE="\033[36m"; RESET="\033[0m"

log_info(){ printf "${BLUE}[*]${RESET} %s\n" "$1"; }
log_success(){ printf "${GREEN}[OK]${RESET} %s\n" "$1"; }
log_warning(){ printf "${YELLOW}[AVISO]${RESET} %s\n" "$1"; }
log_error(){ printf "${RED}[ERRO]${RESET} %s\n" "$1" >&2; }
answer_is_yes(){ [[ "$1" =~ ^([sS]|[yY])$ ]]; }

require_root()
{
    [[ "${CAPIVARA_UNINSTALL_TESTING:-0}" == 1 || "${EUID}" -eq 0 ]] || {
        log_error "Execute utilizando sudo. | Run using sudo."; exit 1;
    }
}

validate_paths()
{
    if [[ "${CAPIVARA_UNINSTALL_TESTING:-0}" != 1 ]]
    then
        [[ "${INSTALL_DIR}" == /opt/dsm ]] || { log_error "Caminho de instalação inválido."; exit 1; }
        [[ "${SYSTEMD_DIR}" == /etc/systemd/system ]] || { log_error "Diretório systemd inválido."; exit 1; }
    fi
    [[ -n "${INSTALL_DIR}" && "${INSTALL_DIR}" != / && "${INSTALL_DIR}" != /opt ]] || {
        log_error "Proteção de caminho recusou ${INSTALL_DIR:-<vazio>}."; exit 1;
    }
    [[ ! -L "${INSTALL_DIR}" ]] || { log_error "O diretório de instalação não pode ser um link."; exit 1; }
}

read_config_value()
{
    local key="$1"
    [[ -f "${CONFIG_FILE}" ]] || return 0
    awk -F= -v key="${key}" '$1==key {v=substr($0,index($0,"=")+1); gsub(/^[[:space:]\047"]+|[[:space:]\047"]+$/,"",v); print v; exit}' "${CONFIG_FILE}"
}

load_config()
{
    if [[ -f "${CONFIG_FILE}" ]]
    then
        # Nunca execute dsm.conf como root; leia só estas chaves.
        DSM_USER="$(read_config_value DSM_USER)"
        DSM_GROUP="$(read_config_value DSM_GROUP)"
        log_info "Identidade de serviço lida da configuração."
    else
        log_warning "dsm.conf não encontrado; a conta de serviço será preservada."
    fi
}

final_backup()
{
    local answer=""
    read -r -p "Criar backup final? (s/N) | Create final backup? (y/N): " answer || true
    if answer_is_yes "${answer}"
    then
        [[ -x "${DSM_LINK}" ]] && "${DSM_LINK}" backup create \
            || log_warning "Comando dsm indisponível ou backup final falhou."
    fi
}

discover_managed_units()
{
    local path name
    local -A seen=()
    local -a paths=()
    shopt -s nullglob
    paths+=(
        "${SYSTEMD_DIR}"/dsm-*.service
        "${SYSTEMD_DIR}"/dsm-*.timer
        "${SYSTEMD_DIR}"/capivara-*.service
        "${SYSTEMD_DIR}"/capivara-*.timer
    )
    shopt -u nullglob
    for path in "${paths[@]}"
    do
        name="$(basename "${path}")"
        if [[ "${name}" == capivara-* ]] \
            && ! grep -Fq -- "${INSTALL_DIR}" "${path}" 2>/dev/null
        then
            continue
        fi
        [[ -n "${seen[${name}]:-}" ]] || { printf '%s\n' "${name}"; seen["${name}"]=1; }
    done
    command -v systemctl >/dev/null 2>&1 || return 0
    while read -r name _
    do
        if [[ "${name}" == capivara-*.service || "${name}" == capivara-*.timer ]]
        then
            systemctl cat "${name}" 2>/dev/null | grep -Fq -- "${INSTALL_DIR}" || continue
        elif [[ "${name}" != dsm-*.service && "${name}" != dsm-*.timer ]]
        then
            continue
        fi
        [[ -n "${seen[${name}]:-}" ]] || { printf '%s\n' "${name}"; seen["${name}"]=1; }
    done < <(
        systemctl list-unit-files \
            'dsm-*.service' 'dsm-*.timer' \
            'capivara-*.service' 'capivara-*.timer' \
            --no-legend 2>/dev/null || true
    )
}

remove_systemd_units()
{
    local unit
    local -a units=()
    mapfile -t units < <(discover_managed_units)
    log_info "Parando e desabilitando ${#units[@]} unit(s) do Capivara/DSM..."
    for unit in "${units[@]}"; do systemctl disable --now "${unit}" 2>/dev/null || true; done
    for unit in "${units[@]}"; do rm -f -- "${SYSTEMD_DIR}/${unit}"; done
    if command -v systemctl >/dev/null 2>&1
    then
        systemctl daemon-reload
        systemctl reset-failed || true
    fi
    log_success "Units systemd removidas."
}

process_parent_pid()
{
    local pid="$1" stat rest
    [[ -r "/proc/${pid}/stat" ]] || return 1
    stat="$(cat "/proc/${pid}/stat" 2>/dev/null)" || return 1
    # comm may contain spaces and parentheses. Strip through the final ') '.
    rest="${stat##*) }"
    set -- ${rest}
    [[ $# -ge 2 ]] || return 1
    printf '%s\n' "$2"
}

process_is_uninstall_ancestor()
{
    local target="$1" pid="$$" parent=""
    while [[ "${pid}" =~ ^[0-9]+$ && "${pid}" -gt 0 ]]
    do
        [[ "${target}" == "${pid}" ]] && return 0
        parent="$(process_parent_pid "${pid}" 2>/dev/null || true)"
        [[ "${parent}" =~ ^[0-9]+$ && "${parent}" -gt 0 && "${parent}" != "${pid}" ]] || break
        pid="${parent}"
    done
    return 1
}

process_references_install()
{
    local pid="$1" kind value arg

    # Nunca encerre o desinstalador, sudo, a shell chamadora, sshd ou qualquer
    # outro ancestral da sessão que iniciou a remoção.
    process_is_uninstall_ancestor "${pid}" && return 1

    # cwd dentro de /opt/dsm NÃO torna um processo gerenciado pelo Capivara.
    # Uma shell SSH pode legitimamente executar `cd /opt/dsm` antes de chamar
    # uninstall.sh. Matar por cwd derruba a sessão e interrompe a remoção.
    for kind in exe
    do
        value="$(readlink "/proc/${pid}/${kind}" 2>/dev/null || true)"
        value="${value% (deleted)}"
        [[ "${value}" == "${INSTALL_DIR}" || "${value}" == "${INSTALL_DIR}/"* ]] && return 0
    done

    [[ -r "/proc/${pid}/cmdline" ]] || return 1
    while IFS= read -r -d '' arg
    do
        [[ "${arg}" == "${INSTALL_DIR}" || "${arg}" == "${INSTALL_DIR}/"* ]] && return 0
    done < "/proc/${pid}/cmdline"
    return 1
}

find_install_processes()
{
    local proc pid
    for proc in /proc/[0-9]*
    do
        [[ -d "${proc}" ]] || continue
        pid="${proc##*/}"
        process_references_install "${pid}" && printf '%s\n' "${pid}"
    done
}

stop_residual_processes()
{
    local attempt
    local -a pids=()
    mapfile -t pids < <(find_install_processes)
    ((${#pids[@]})) || return 0
    log_warning "Encerrando processos gerenciados vinculados a ${INSTALL_DIR}: ${pids[*]}"
    kill -TERM "${pids[@]}" 2>/dev/null || true
    for attempt in 1 2 3 4 5
    do
        sleep 1; mapfile -t pids < <(find_install_processes); ((${#pids[@]})) || return 0
    done
    log_warning "Forçando encerramento: ${pids[*]}"
    kill -KILL "${pids[@]}" 2>/dev/null || true
    sleep 1
}

remove_commands()
{
    local link
    for link in "${DSM_LINK}" "${CAP_LINK}"
    do
        [[ -e "${link}" || -L "${link}" ]] || continue
        rm -f -- "${link}"; log_success "Comando removido: ${link}"
    done
}

remove_installation()
{
    validate_paths
    if [[ -e "${INSTALL_DIR}" ]]
    then
        rm -rf -- "${INSTALL_DIR}"; log_success "Diretório ${INSTALL_DIR} removido."
    else
        log_warning "Instalação em ${INSTALL_DIR} não encontrada."
    fi
}

remove_external_backup()
{
    local answer=""
    [[ -d "${BACKUP_DIR}" ]] || return 0
    read -r -p "Remover também ${BACKUP_DIR}? (s/N) | Remove it too? (y/N): " answer || true
    if answer_is_yes "${answer}"
    then
        [[ "${BACKUP_DIR}" == /opt/dsm-backup || "${CAPIVARA_UNINSTALL_TESTING:-0}" == 1 ]] \
            || { log_error "Proteção de caminho recusou ${BACKUP_DIR}."; return 1; }
        rm -rf -- "${BACKUP_DIR}"; log_success "Backup externo removido."
    else
        log_info "Backup externo preservado."
    fi
}

remove_service_account()
{
    local answer="" entry account_uid home shell uid_min gid
    if [[ "${DSM_USER}:${DSM_GROUP}" != capivara:capivara ]]
    then
        log_info "Conta preservada: capivara:capivara não foi confirmada na configuração."; return 0
    fi
    read -r -p "Remover a conta capivara:capivara? (s/N) | Remove service account? (y/N): " answer || true
    answer_is_yes "${answer}" || { log_info "Conta capivara:capivara preservada por padrão."; return 0; }

    entry="$(getent passwd capivara || true)"
    if [[ -n "${entry}" ]]
    then
        IFS=: read -r _ _ account_uid _ _ home shell <<<"${entry}"
        uid_min="$(awk '$1=="UID_MIN"{print $2;exit}' /etc/login.defs 2>/dev/null || true)"; uid_min="${uid_min:-1000}"
        if ((account_uid >= uid_min)) || [[ "${home}" != /opt/dsm ]] \
            || [[ "${shell}" != */nologin && "${shell}" != */false ]]
        then
            log_error "A conta capivara não parece ter sido criada pelo instalador; preservando-a."; return 1
        fi
        pgrep -u capivara >/dev/null 2>&1 && { log_error "A conta capivara ainda possui processos."; return 1; }
        userdel capivara; log_success "Usuário capivara removido sem apagar dados externos."
    fi
    if getent group capivara >/dev/null 2>&1
    then
        gid="$(getent group capivara | cut -d: -f3)"
        getent passwd | awk -F: -v gid="${gid}" '$4==gid{found=1} END{exit !found}' \
            && { log_error "Grupo capivara ainda é primário de outra conta."; return 1; }
        [[ -z "$(getent group capivara | cut -d: -f4)" ]] \
            || { log_error "Grupo capivara ainda possui membros."; return 1; }
        groupdel capivara; log_success "Grupo capivara removido."
    fi
}

validate_uninstall()
{
    local link failures=0
    local -a processes=() units=()
    [[ ! -e "${INSTALL_DIR}" && ! -L "${INSTALL_DIR}" ]] \
        || { log_error "Validação: ${INSTALL_DIR} ainda existe."; ((failures+=1)); }
    mapfile -t processes < <(find_install_processes)
    ((${#processes[@]}==0)) || { log_error "Validação: processos residuais: ${processes[*]}"; ((failures+=1)); }
    mapfile -t units < <(discover_managed_units)
    ((${#units[@]}==0)) || { log_error "Validação: units residuais: ${units[*]}"; ((failures+=1)); }
    for link in "${DSM_LINK}" "${CAP_LINK}"
    do
        [[ ! -e "${link}" && ! -L "${link}" ]] \
            || { log_error "Validação: comando/link residual: ${link}"; ((failures+=1)); }
    done
    ((failures==0)) || { log_error "Desinstalação incompleta: ${failures} validação(ões) falharam."; return 1; }
    log_success "Validação pós-desinstalação concluída sem resíduos."
}

confirm_remove()
{
    local answer=""
    echo "============================================================"
    echo " Remover | Remove ${DSM_NAME}"
    echo "============================================================"
    echo "Remove ${INSTALL_DIR}, units dsm-* e comandos dsm/cap."
    echo "Preserva por padrão servidores, dados externos, mods, backups e a conta de serviço."
    read -r -p "Continuar? (s/N) | Continue? (y/N): " answer || true
    answer_is_yes "${answer}" || { echo "Cancelado | Cancelled."; exit 0; }
}

main()
{
    require_root; validate_paths; confirm_remove; load_config; final_backup
    remove_systemd_units; stop_residual_processes; remove_commands; remove_installation
    remove_external_backup; remove_service_account; validate_uninstall
    log_success "${DSM_NAME} removido com sucesso."
}

[[ "${BASH_SOURCE[0]}" != "$0" ]] || main "$@"
