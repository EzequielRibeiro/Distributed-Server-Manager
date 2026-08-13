#!/bin/bash

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

FILE="$DSM_ROOT/runtime/events/history.json"

CATEGORY="$1"

jq --arg cat "$CATEGORY" \
'.[] | select(.category==$cat)' \
"$FILE"