#!/bin/bash

# =============================================================
# DSM Combat Statistics
# Commit 12
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


STATE="$DSM_ROOT/runtime/combat/state.json"



case "$1" in


top)

jq '
to_entries |
sort_by(
.value.kills
) |
reverse |
.[0:10]
' "$STATE"


;;



*)

echo "

Combat Statistics


statistics.sh top


"

;;

esac