#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${ROOT}/install-core-engine.sh"

[[ -f "${ENGINE}" ]] || {
    printf '[Capivara][ERRO] Motor do instalador ausente: %s\n' "${ENGINE}" >&2
    exit 1
}

# shellcheck source=install-core-engine.sh
source "${ENGINE}"

# The public and installed CLI contract is cap-only. Keep the monolithic
# engine's internal path variables pointed at the canonical CLI until their
# historical names are removed from the engine itself.
DSM_BIN="${CAP_BIN}"
DSM_LINK="${CAP_LINK}"

local_source_available()
{
    [[ -f "${INSTALLER_DIR}/version" ]] \
        && [[ -f "${INSTALLER_DIR}/bin/cap" ]] \
        && [[ -f "${INSTALLER_DIR}/core/bootstrap.sh" ]] \
        && [[ -f "${INSTALLER_DIR}/config/dsm.conf" ]]
}

verify_source_tree()
{
    local -a required=(
        version
        bin/cap
        core/bootstrap.sh
        core/semver.sh
        core/archive_security.sh
        core/archive_inspector.py
        config/dsm.conf
        database/manager.py
        database/registry.py
        database/registry_repository.py
        database/runtime_backend.py
        database/backend_factory.py
        database/schemas/sqlite.sql
        database/schemas/postgresql.sql
        database/schemas/mysql.sql
        database/schemas/mariadb.sql
        installer/database_setup.sh
        systemd/dsm-dashboard.service
    )
    local -a missing=()
    local relative
    for relative in "${required[@]}"; do
        [[ -e "${DSM_SOURCE}/${relative}" ]] || missing+=("${relative}")
    done
    if (( ${#missing[@]} > 0 )); then
        printf '[Capivara][ERRO] Pacote incompleto:\n' >&2
        printf '  - %s\n' "${missing[@]}" >&2
        exit 1
    fi
}

# The outer install.sh already chooses controller/agent/hybrid. When that value
# is present, do not present the role catalogue a second time; only collect any
# still-missing service-account fields.
select_installation_profile()
{
    local role_preselected=0

    [[ -n "${DSM_NODE_ROLE:-}" ]] && role_preselected=1

    if (( role_preselected == 0 ))
    then
        section "Perfil deste node"

        if is_interactive
        then
            cat <<'EOF_ROLE'
Papéis disponíveis:

  controller
      Controlador central. Não executa servidores de jogos.

  agent
      Executa e administra instâncias de jogos.

  hybrid
      Controller e Agent na mesma máquina.
EOF_ROLE
        fi
    elif [[ -z "${DSM_SERVICE_USER:-}" || -z "${DSM_SERVICE_GROUP:-}" ]]
    then
        section "Conta de serviço"
    fi

    prompt_value DSM_SERVICE_USER "Usuário de serviço" "${CURRENT_MACHINE_USER}"
    prompt_value DSM_SERVICE_GROUP "Grupo de serviço" "${CURRENT_MACHINE_GROUP}"

    if (( role_preselected == 0 ))
    then
        prompt_value DSM_NODE_ROLE "Papel (controller/agent/hybrid)" "agent"
    fi

    validate_account_name "${DSM_SERVICE_USER}" "Usuário"
    validate_account_name "${DSM_SERVICE_GROUP}" "Grupo"

    case "${DSM_NODE_ROLE}" in
        controller|agent|hybrid) ;;
        *) die "DSM_NODE_ROLE inválido: ${DSM_NODE_ROLE}" ;;
    esac
}

# Preserve the database manager exit status across the temporary DSM_ROOT swap.
run_source_database_manager()
{
    local saved_root="${DSM_ROOT}"
    local status=0

    DSM_ROOT="${DSM_SOURCE}"
    run_database_manager "$@" || status=$?
    DSM_ROOT="${saved_root}"

    return "${status}"
}

# Keep the generic requirements report intact, then add a role-aware feature
# report for Controller capabilities that rely on optional system packages.
eval "$(declare -f system_requirements_preflight | sed '1s/system_requirements_preflight/system_requirements_preflight_base/')"

controller_feature_requirements()
{
    case "${DSM_NODE_ROLE:-}" in
        controller|hybrid) ;;
        *) return 0 ;;
    esac

    section "Dependências por recurso"
    printf 'Recursos administrativos do Controller podem exigir pacotes adicionais.\n\n'

    if command -v ssh >/dev/null 2>&1
    then
        printf '  %-30s OK\n' "OpenSSH Client"
        printf '      Recurso: deploy/teste remoto de Agents por chave SSH.\n'
    else
        printf '  %-30s AVISO - comando ssh não encontrado\n' "OpenSSH Client"
        printf '      Recurso afetado: cap agent deploy/test-connection.\n'
        printf '      Debian/Ubuntu: sudo apt install openssh-client\n'
    fi

    if command -v sshpass >/dev/null 2>&1
    then
        printf '  %-30s OK\n' "sshpass"
        printf '      Recurso: autenticação SSH por --password-file.\n'
    else
        printf '  %-30s AVISO - necessário para --password-file\n' "sshpass"
        printf '      Recurso afetado: cap agent deploy/test-connection por senha.\n'
        printf '      Debian/Ubuntu: sudo apt install sshpass\n'
        printf '      Alternativa preferida: autenticação por chave SSH.\n'
    fi
}

system_requirements_preflight()
{
    system_requirements_preflight_base "$@"
    controller_feature_requirements
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    main "$@"
fi
