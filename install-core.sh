#!/usr/bin/env bash
set -Eeuo pipefail

# Compatibility entrypoint kept small so install.sh remains stable while the
# implementation can be hardened without duplicating the interactive wizard.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${ROOT}/install-core-engine.sh"

[[ -f "${ENGINE}" ]] || {
    printf '[Capivara][ERRO] Motor do instalador ausente: %s\n' "${ENGINE}" >&2
    exit 1
}

# shellcheck source=install-core-engine.sh
source "${ENGINE}"

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

    prompt_value \
        DSM_SERVICE_USER \
        "Usuário de serviço" \
        "${CURRENT_MACHINE_USER}"

    prompt_value \
        DSM_SERVICE_GROUP \
        "Grupo de serviço" \
        "${CURRENT_MACHINE_GROUP}"

    if (( role_preselected == 0 ))
    then
        prompt_value \
            DSM_NODE_ROLE \
            "Papel (controller/agent/hybrid)" \
            "agent"
    fi

    validate_account_name \
        "${DSM_SERVICE_USER}" \
        "Usuário"

    validate_account_name \
        "${DSM_SERVICE_GROUP}" \
        "Grupo"

    case "${DSM_NODE_ROLE}" in
        controller|agent|hybrid)
            ;;
        *)
            die "DSM_NODE_ROLE inválido: ${DSM_NODE_ROLE}"
            ;;
    esac
}

# Preserve the database manager exit status across the temporary DSM_ROOT swap.
# Without this, restoring DSM_ROOT becomes the function's final successful
# command and can turn an authentication failure into a false positive.
run_source_database_manager()
{
    local saved_root="${DSM_ROOT}"
    local status=0

    DSM_ROOT="${DSM_SOURCE}"
    run_database_manager "$@" || status=$?
    DSM_ROOT="${saved_root}"

    return "${status}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]
then
    main "$@"
fi
