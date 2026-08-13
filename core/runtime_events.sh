#!/usr/bin/env bash

set -Eeuo pipefail


EVENT_FILE="/opt/dsm/runtime/events.json"


runtime_event()
{

TYPE="$1"
MESSAGE="$2"


python3 <<PY

import json
import datetime
import os


file="${EVENT_FILE}"


if os.path.exists(file):

    with open(file) as f:
        events=json.load(f)

else:

    events=[]



events.append({

"type":"${TYPE}",

"message":"${MESSAGE}",

"time":
datetime.datetime.utcnow()
.isoformat()

})



with open(file,"w") as f:

    json.dump(
        events,
        f,
        indent=4
    )

PY

}