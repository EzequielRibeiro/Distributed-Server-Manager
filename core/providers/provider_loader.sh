#!/bin/bash


load_provider()
{

if [[ -f "${DSM_ROOT}/core/providers/provider.sh" ]]
    then
        source "${DSM_ROOT}/core/providers/provider.sh"
    fi


    case "${DSM_PROVIDER:-linuxgsm}" in


        linuxgsm)

            source "${DSM_ROOT}/core/providers/linuxgsm.sh"
        ;;


        native)

            source "${DSM_ROOT}/core/providers/native.sh"
        ;;


        *)

            echo "Provider desconhecido:"
            echo "${DSM_PROVIDER}"

            return 1
        ;;

    esac

}