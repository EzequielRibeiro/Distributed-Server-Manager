#!/bin/bash
# =============================================================
# mods/log.sh - MÓDULO 03 (MODS)
# Visualização de logs do módulo Mods DSM
# Responsável por:
# - listar logs
# - visualizar logs recentes
# - filtrar eventos de mods
# NÃO FAZ:
# - instalação
# - atualização
# - sincronização
# - alteração de arquivos
# =============================================================

LOG_MODULE="mods"

# =============================================================
# Bootstrap
# =============================================================
if [ -z "${DSM_ROOT:-}" ]
then
    export DSM_ROOT="/opt/dsm"
fi

source "${DSM_ROOT}/core/bootstrap.sh"

# =============================================================
# Diretórios
# =============================================================
DSM_LOG_DIR="${DSM_ROOT}/logs"
MOD_LOG_PREFIX="mods"

# =============================================================
# Listar logs
# Uso:
# mods_log_list
# =============================================================
mods_log_list()
{
    if [ ! -d "${DSM_LOG_DIR}" ]
    then
        log_warn \
        "Diretório de logs inexistente."
        return 1
    fi

    find "${DSM_LOG_DIR}" \
        -type f \
        -name "*.log" \
        -printf "%f\n" \
        | grep "${MOD_LOG_PREFIX}" || true
}

# =============================================================
# Mostrar log principal
# Uso:
# mods_log_show
# =============================================================
mods_log_show()
{
    local file
    file="${DSM_LOG_DIR}/mods.log"

    if [ ! -f "${file}" ]
    then
        log_warn \
        "Arquivo de log não encontrado:"
        echo "${file}"
        return 1
    fi

    cat "${file}"
}

# =============================================================
# Últimas linhas
# Uso:
# mods_log_tail 100
# =============================================================
mods_log_tail()
{
    local lines="${1:-50}"
    local file
    file="${DSM_LOG_DIR}/mods.log"

    if [ ! -f "${file}" ]
    then
        log_warn \
        "Log Mods inexistente."
        return 1
    fi

    tail \
        -n "${lines}" \
        "${file}"
}

# =============================================================
# Buscar evento
# Uso:
# mods_log_grep erro
# =============================================================
mods_log_grep()
{
    local query="$1"

    if [ -z "${query}" ]
    then
        log_error \
        "Informe termo de busca."
        return 1
    fi

    grep \
        -i \
        "${query}" \
        "${DSM_LOG_DIR}/mods.log"
}

# =============================================================
# Eventos DSM
# Lê:
# events.log
# =============================================================
mods_log_events()
{
    local file
    file="${DSM_LOG_DIR}/events.log"

    if [ ! -f "${file}" ]
    then
        log_warn \
        "Arquivo events.log não encontrado."
        return 1
    fi

    grep \
        "mods\." \
        "${file}"
}

# =============================================================
# Limpar logs antigos
# Uso:
# mods_log_rotate
# =============================================================
mods_log_rotate()
{
    local days="${1:-30}"

    find "${DSM_LOG_DIR}" \
        -name "mods*.log" \
        -mtime +"${days}" \
        -delete

    log_ok \
    "Logs antigos removidos."
}

# =============================================================
# Dispatcher
# =============================================================
mods_log_command()
{
case "${1:-}" in
list)
    mods_log_list
;;
show)
    mods_log_show
;;
tail)
    mods_log_tail "$2"
;;
grep)
    mods_log_grep "$2"
;;
events)
    mods_log_events
;;
rotate)
    mods_log_rotate "$2"
;;
*)
cat <<EOF

Uso:

 mods_log.sh list

 mods_log.sh show

 mods_log.sh tail [linhas]

 mods_log.sh grep termo

 mods_log.sh events

 mods_log.sh rotate [dias]

EOF
return 1
;;
esac
}

# =============================================================
# Execução direta
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    mods_log_command "$@"
fi
