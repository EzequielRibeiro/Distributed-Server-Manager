#!/usr/bin/env bash

# =============================================================
# Capivara DSM — Semantic Versioning helpers
# =============================================================
#
# Contrato compartilhado para validação e comparação de versões
# seguindo a precedência SemVer.
#
# semver_compare LEFT RIGHT
#
# Retorno pela saída padrão:
#   -1  LEFT < RIGHT
#    0  LEFT = RIGHT
#    1  LEFT > RIGHT
#
# Build metadata (+...) não participa da precedência.
# =============================================================

is_semver() {
    [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]
}

semver_compare() {
    local LEFT="${1%%+*}"
    local RIGHT="${2%%+*}"
    local LEFT_CORE="${LEFT%%-*}"
    local RIGHT_CORE="${RIGHT%%-*}"
    local LEFT_PRE=""
    local RIGHT_PRE=""
    local -a LEFT_PARTS RIGHT_PARTS LEFT_IDS RIGHT_IDS
    local INDEX MAX LEFT_ID RIGHT_ID

    [[ "${LEFT}" == *-* ]] && LEFT_PRE="${LEFT#*-}"
    [[ "${RIGHT}" == *-* ]] && RIGHT_PRE="${RIGHT#*-}"

    IFS=. read -r -a LEFT_PARTS <<<"${LEFT_CORE}"
    IFS=. read -r -a RIGHT_PARTS <<<"${RIGHT_CORE}"

    for INDEX in 0 1 2
    do
        if ((10#${LEFT_PARTS[INDEX]} < 10#${RIGHT_PARTS[INDEX]}))
        then
            echo -1
            return
        fi

        if ((10#${LEFT_PARTS[INDEX]} > 10#${RIGHT_PARTS[INDEX]}))
        then
            echo 1
            return
        fi
    done

    if [[ -z "${LEFT_PRE}" && -z "${RIGHT_PRE}" ]]
    then
        echo 0
        return
    fi

    if [[ -z "${LEFT_PRE}" ]]
    then
        echo 1
        return
    fi

    if [[ -z "${RIGHT_PRE}" ]]
    then
        echo -1
        return
    fi

    IFS=. read -r -a LEFT_IDS <<<"${LEFT_PRE}"
    IFS=. read -r -a RIGHT_IDS <<<"${RIGHT_PRE}"

    MAX=${#LEFT_IDS[@]}
    ((${#RIGHT_IDS[@]} > MAX)) && MAX=${#RIGHT_IDS[@]}

    for ((INDEX = 0; INDEX < MAX; INDEX++))
    do
        LEFT_ID="${LEFT_IDS[INDEX]:-}"
        RIGHT_ID="${RIGHT_IDS[INDEX]:-}"

        [[ -z "${LEFT_ID}" ]] && {
            echo -1
            return
        }

        [[ -z "${RIGHT_ID}" ]] && {
            echo 1
            return
        }

        [[ "${LEFT_ID}" == "${RIGHT_ID}" ]] && continue

        if [[ "${LEFT_ID}" =~ ^[0-9]+$ && "${RIGHT_ID}" =~ ^[0-9]+$ ]]
        then
            if ((10#${LEFT_ID} < 10#${RIGHT_ID}))
            then
                echo -1
            else
                echo 1
            fi
        elif [[ "${LEFT_ID}" =~ ^[0-9]+$ ]]
        then
            echo -1
        elif [[ "${RIGHT_ID}" =~ ^[0-9]+$ ]]
        then
            echo 1
        elif [[ "${LEFT_ID}" < "${RIGHT_ID}" ]]
        then
            echo -1
        else
            echo 1
        fi

        return
    done

    echo 0
}
