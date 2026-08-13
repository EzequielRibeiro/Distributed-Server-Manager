#!/bin/bash

DSM_ROOT="/opt/dsm"

RUNTIME_API="$DSM_ROOT/runtime/api/dashboard.sh"


case "$1" in


summary)

SERVER="$2"
GAME="$3"
INSTANCE="$4"


if [ -z "$SERVER" ] || [ -z "$GAME" ] || [ -z "$INSTANCE" ]
then
    echo "{}"
    exit 1
fi


bash "$RUNTIME_API" \
summary \
"$SERVER" \
"$GAME" \
"$INSTANCE"


;;


*)

echo "
Uso:

runtime.sh summary server game instance

"

exit 1

;;


esac