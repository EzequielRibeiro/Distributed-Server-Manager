runtime_metric_get()
{
    local KEY="$1"

    runtime_get metrics |
    python3 - "$KEY" <<'PY'
import json
import sys

key=sys.argv[1]

try:
    data=json.load(sys.stdin)

    value=data

    for part in key.split("."):
        value=value.get(part,"-")

    print(value)

except Exception:
    print("-")
PY
}