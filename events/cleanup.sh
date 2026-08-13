#!/bin/bash

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

FILE="$DSM_ROOT/runtime/events/history.json"

KEEP="${1:-5000}"

TMP=$(mktemp)

jq \
--argjson keep "$KEEP" \
'. | reverse | .[0:$keep] | reverse' \
"$FILE" \
> "$TMP"

mv "$TMP" "$FILE"