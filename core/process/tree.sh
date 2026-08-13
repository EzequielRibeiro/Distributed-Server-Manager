#!/usr/bin/env bash
# =============================================================
# Capivara Distributed Server Manager
#
# Process Tree Manager
#
# Responsável por:
#
# - identificar árvore de processos
# - listar filhos
# - encerrar árvore completa
#
# =============================================================


set -Eeuo pipefail


# =============================================================
# Retorna filhos diretos de um PID
# =============================================================

process_children()
{

local PID="$1"


if [[ -z "${PID}" ]]
then
    return 1
fi


pgrep -P "${PID}" 2>/dev/null || true

}



# =============================================================
# Retorna todos os descendentes
#
# Pai
#  |
#  +-- filho
#       |
#       +-- neto
#
# =============================================================

process_descendants()
{

local PID="$1"


local CHILDREN


CHILDREN=$(process_children "${PID}")


for CHILD in ${CHILDREN}
do

    process_descendants "${CHILD}"

    echo "${CHILD}"

done

}



# =============================================================
# Mostra árvore completa
# =============================================================

process_tree()
{

local PID="$1"


if ! kill -0 "${PID}" 2>/dev/null
then
    echo "Processo inexistente:"
    echo "${PID}"
    return 1
fi



echo
echo "Process Tree"
echo "-------------"


pstree -p "${PID}" 2>/dev/null || {


echo "${PID}"


for CHILD in $(process_descendants "${PID}")
do

    echo " └─ ${CHILD}"

done


}


}



# =============================================================
# Retorna PID + filhos
#
# usado pelo stop/recovery
#
# =============================================================

process_tree_pids()
{

local PID="$1"


echo "${PID}"


process_descendants "${PID}"

}



# =============================================================
# Mata árvore completa
#
# Ordem:
#
# filhos primeiro
# pai por último
#
# =============================================================

process_kill_tree()
{

local PID="$1"


if ! kill -0 "${PID}" 2>/dev/null
then
    return 0
fi



echo "Encerrando árvore:"
echo "${PID}"



# Primeiro filhos

for CHILD in $(process_descendants "${PID}")
do

    echo "Finalizando filho:"
    echo "${CHILD}"

    kill -TERM "${CHILD}" 2>/dev/null || true

done



sleep 3



# Depois pai

echo "Finalizando principal:"
echo "${PID}"


kill -TERM "${PID}" 2>/dev/null || true



sleep 5



# Força se necessário

if kill -0 "${PID}" 2>/dev/null
then

    echo "Forçando encerramento."

    for CHILD in $(process_tree_pids "${PID}")
    do

        kill -KILL "${CHILD}" 2>/dev/null || true

    done

fi


}