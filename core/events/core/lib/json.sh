#!/bin/bash

json_value()
{
    local FILE="$1"
    local KEY="$2"

    if [[ ! -f "$FILE" ]]
    then
        echo "-"
        return
    fi

    python3 - "$FILE" "$KEY" <<'PY'
import json
import sys

file=sys.argv[1]
key=sys.argv[2]

try:
    with open(file) as f:
        data=json.load(f)

    print(data.get(key,"-"))

except Exception:
    print("-")
PY
}