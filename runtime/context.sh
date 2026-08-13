#!/bin/sh
#
# DSM Runtime Context
#
# Responsável:
# - contexto do servidor atual
# - game
# - instance
# - caminhos runtime
# - carregamento manifesto
#


###############################################################################
# Inicialização
###############################################################################



runtime_context_init()
{

       : "${DSM_HOST:=$(runtime_host)}"

       : "${DSM_NODE:=server01}"

       : "${DSM_GAME:=$(runtime_game)}"

       : "${DSM_INSTANCE:=$(runtime_instance)}"


        export DSM_HOST
        export DSM_NODE
        export DSM_GAME
        export DSM_INSTANCE

}



###############################################################################
# Recursos
###############################################################################

runtime_resource_path()
{

    echo \
    "${DSM_ROOT}/runtime/resources/${DSM_SERVER}/${DSM_GAME}/${DSM_INSTANCE}"

}



runtime_resource_init()
{

    local server="$1"
    local game="$2"
    local instance="$3"
    local path

    path="${DSM_ROOT}/runtime/resources/${server}/${game}/${instance}"


     mkdir -p "$path"

    echo "$path"

}



###############################################################################
# Identidade
###############################################################################

runtime_context_server()
{
    echo "$DSM_SERVER"
}



runtime_context_game()
{
    echo "$DSM_GAME"
}



runtime_context_instance()
{
    echo "$DSM_INSTANCE"
}



###############################################################################
# Manifesto
###############################################################################

runtime_manifest()
{

    local section=""
    local line
    local key
    local value


    while IFS= read -r line
    do

        line="$(printf "%s" "$line" | xargs)"


        [ -z "$line" ] && continue


        case "$line" in

            \#*)
                continue
            ;;


            \[*\])

                section="${line#[}"
                section="${section%]}"

                continue

            ;;

        esac



        key="${line%%=*}"

        value="${line#*=}"



        key=$(printf "%s" "$key" \
        | tr '[:lower:]' '[:upper:]')



        section=$(printf "%s" "$section" \
        | tr '[:lower:]' '[:upper:]')



        runtime_set \
        "${section}_${key}" \
        "$value"


    done

}