#!/bin/bash
# =============================================================
# doctor/formatter.sh
#
# DSM Doctor Presentation Layer
#
# Apenas apresentação CLI
#
# Não altera Runtime
#
# =============================================================

doctor_format_status()
{
    local json="$1"

    local score
    local max

    score=$(echo "$json" | jq -r '.score')
    max=$(echo "$json" | jq -r '.max')


    echo
    echo "================================================="
    echo " DSM Doctor"
    echo "================================================="
    echo


    if [[ "$score" == "$max" ]]
    then
        echo "Status: HEALTHY"
    else
        echo "Status: WARNING"
    fi


    echo
    echo "Score:"
    echo "${score}/${max}"

    echo
    echo "Checks:"
    echo


    echo "$json" |
    jq -r '
    .report[] |
    "\(.ok)|\(.label)|\(.detail)"
    ' |
    while IFS="|" read -r ok label detail
    do

        if [[ "$ok" == "true" ]]
        then
            symbol="✓"
        else
            symbol="✗"
        fi


        echo "${symbol} ${label}"
        echo "  ${detail}"
        echo

    done
}