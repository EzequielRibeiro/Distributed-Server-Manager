#!/bin/bash
# =============================================================
# mods/verify.sh - MÓDULO 03 (MODS)
# DayZ Server Manager
# Verificação de integridade dos Mods DayZ
# Responsável por verificar:
#   • existência do mod
#   • diretório addons
#   • arquivos PBO
#   • arquivos meta.cpp
#   • arquivos Keys (.bikey)
# Utilizado por:
#   dsm mods verify
#   dsm doctor
# =============================================================

export LOG_MODULE="mods"

# =============================================================
# Ambiente DSM
# =============================================================
if [[ -z "${DSM_ROOT:-}" ]]; then
    echo "DSM_ROOT não definido."
    return 1 2>/dev/null || exit 1
fi

# =============================================================
# Bootstrap
# =============================================================
BOOTSTRAP="${DSM_ROOT}/core/bootstrap.sh"
if [[ ! -f "${BOOTSTRAP}" ]]; then
    echo "Bootstrap não encontrado:"
    echo "${BOOTSTRAP}"
    return 1 2>/dev/null || exit 1
fi

# shellcheck source=/dev/null
source "${BOOTSTRAP}"

# =============================================================
# Configuração DSM
# =============================================================
DSM_CONFIG="${DSM_ROOT}/config/dsm.conf"
if [[ ! -f "${DSM_CONFIG}" ]]; then
    log_error "Arquivo de configuração não encontrado:"
    echo "${DSM_CONFIG}"
    return 1 2>/dev/null || exit 1
fi

# shellcheck source=/dev/null
source "${DSM_CONFIG}"

# =============================================================
# Variáveis
# =============================================================
MODS_DIR="${SERVERFILES_PATH}/mods"
KEYS_DIR="${SERVERFILES_PATH}/keys"
VERIFY_ERRORS=0
VERIFY_WARNINGS=0
VERIFY_MODS=0

# =============================================================
# Helpers
# =============================================================
print_separator()
{
    echo "----------------------------------------"
}

verify_fail()
{
    VERIFY_ERRORS=$((VERIFY_ERRORS + 1))
}

verify_warn()
{
    VERIFY_WARNINGS=$((VERIFY_WARNINGS + 1))
}

# =============================================================
# Verificar um Mod
# Uso:
#   verify_mod "@CF"
# =============================================================
verify_mod()
{
    local mod="$1"
    local mod_path="${MODS_DIR}/${mod}"
    print_title "Verificando ${mod}"
    VERIFY_MODS=$((VERIFY_MODS + 1))

    # Diretório existe?
    if [[ ! -d "${mod_path}" ]]; then
        print_fail "Mod não encontrado."
        echo "Local..........: ${mod_path}"
        verify_fail
        return 1
    fi

    print_ok "Diretório encontrado."
    echo "Local..........: ${mod_path}"

    # Diretório Addons
    if [[ -d "${mod_path}/addons" ]]; then
        print_ok "Diretório addons encontrado."
    else
        print_warn "Diretório addons não encontrado."
        verify_warn
    fi

    # Arquivos PBO
    local pbo_count=0
    pbo_count="$(
        find -L "${mod_path}" \
            -type f \
            -iname "*.pbo" \
            2>/dev/null |
        wc -l
    )"

    if (( pbo_count > 0 )); then
        print_ok "Arquivos PBO encontrados."
        echo "Quantidade.....: ${pbo_count}"
    else
        print_fail "Nenhum arquivo PBO encontrado."
        verify_fail
    fi

    # meta.cpp
    if [[ -f "${mod_path}/meta.cpp" ]]; then
        print_ok "Arquivo meta.cpp encontrado."
    else
        print_warn "Arquivo meta.cpp não encontrado."
        verify_warn
    fi

    # Keys
    local key_count=0
    key_count="$(
        find -L "${mod_path}" \
            -type f \
            \( \
                -ipath "*/Keys/*.bikey" \
                -o \
                -ipath "*/keys/*.bikey" \
            \) \
            2>/dev/null |
        wc -l
    )"

    if (( key_count > 0 )); then
        print_ok "Keys encontradas."
        echo "Quantidade.....: ${key_count}"
    else
        print_warn "Nenhuma Key encontrada."
        verify_warn
    fi

    return 0
}

# =============================================================
# Verificar todos os Mods
# =============================================================
verify_all_mods()
{
    print_title "Verificação de Integridade dos Mods"
    VERIFY_ERRORS=0
    VERIFY_WARNINGS=0
    VERIFY_MODS=0

    # Diretório principal
    if [[ ! -d "${MODS_DIR}" ]]; then
        print_fail "Diretório de mods não encontrado."
        echo "Local..........: ${MODS_DIR}"
        return 1
    fi

    # Existe pelo menos um mod?
    if ! find -L "${MODS_DIR}" \
        -mindepth 1 \
        -maxdepth 1 \
        -type d \
        -name "@*" \
        -print -quit | grep -q .
    then
        print_warn "Nenhum mod instalado."
        return 0
    fi

    # Verificar todos os mods
    while IFS= read -r mod
    do
        verify_mod "$(basename "${mod}")"
    done < <(
        find -L "${MODS_DIR}" \
            -mindepth 1 \
            -maxdepth 1 \
            -type d \
            -name "@*" |
        sort
    )

    # Resumo
    print_title "Resumo da Verificação"
    echo "Mods verificados.: ${VERIFY_MODS}"
    echo "Warnings.........: ${VERIFY_WARNINGS}"
    echo "Erros............: ${VERIFY_ERRORS}"
    print_separator

    if (( VERIFY_ERRORS == 0 )); then
        if (( VERIFY_WARNINGS == 0 )); then
            print_ok "Todos os mods estão íntegros."
        else
            print_warn "Verificação concluída com avisos."
        fi
        return 0
    fi

    print_fail "Foram encontrados problemas nos mods."
    return 1
}

# =============================================================
# Dispatcher
# Utilizado pelo módulo mods/mods.sh
# =============================================================
verify_command()
{
    case "${1:-all}" in
        all)
            verify_all_mods
            ;;
        *)
            verify_mod "$1"
            ;;
    esac
}

# =============================================================
# Compatibilidade
# Mantido para versões anteriores do DSM.
# =============================================================
verify_run()
{
    verify_command "$@"
}

# =============================================================
# API simples (Dashboard)
# =============================================================
verify_status_json()
{
    cat <<EOF
{
  "mods":"${VERIFY_MODS}",
  "warnings":"${VERIFY_WARNINGS}",
  "errors":"${VERIFY_ERRORS}",
  "status":"$(
      if [[ "${VERIFY_ERRORS}" -eq 0 ]]; then
          if [[ "${VERIFY_WARNINGS}" -eq 0 ]]; then
              echo healthy
          else
              echo warning
          fi
      else
          echo critical
      fi
  )"
}
EOF
}

# =============================================================
# Execução direta
# Executa somente quando chamado diretamente:
#   ./verify.sh
#   ./verify.sh all
#   ./verify.sh @CF
# Quando carregado via:
#   source verify.sh
# nenhuma função será executada automaticamente.
# =============================================================
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    verify_command "$@"
fi
