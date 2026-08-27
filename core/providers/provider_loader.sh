#!/usr/bin/env bash

load_provider()
{
    if [[ -f "${DSM_ROOT}/core/providers/provider.sh" ]]
    then
        # shellcheck source=/dev/null
        source "${DSM_ROOT}/core/providers/provider.sh"
    fi

    case "${DSM_PROVIDER:-native}" in
        native)
            # shellcheck source=/dev/null
            source "${DSM_ROOT}/core/providers/native.sh"
            ;;
        *)
            echo "Provider não suportado: ${DSM_PROVIDER}" >&2
            return 1
            ;;
    esac
}
