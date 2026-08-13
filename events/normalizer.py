#!/usr/bin/env python3

import json
import sys
import time
import uuid


def create_event(
    event_type,
    category,
    source,
    message,
    severity="INFO",
    data=None
):

    return {

        "id":
            "evt-" + str(uuid.uuid4())[:8],

        "type":
            event_type,

        "category":
            category,

        "severity":
            severity,

        "source":
            source,

        "timestamp":
            int(time.time()),

        "data":
        {
            "message": message,
            **(data or {})
        }
    }



def main():

    raw=sys.stdin.read()

    if not raw:
        return


    try:

        payload=json.loads(raw)


        event=create_event(

            payload.get(
                "type",
                "UNKNOWN"
            ),

            payload.get(
                "category",
                "system"
            ),

            payload.get(
                "source",
                "unknown"
            ),

            payload.get(
                "message",
                ""
            ),

            payload.get(
                "severity",
                "INFO"
            ),

            payload.get(
                "data",
                {}
            )

        )


        print(
            json.dumps(
                event,
                indent=4
            )
        )


    except Exception as e:

        print(
            json.dumps(
                {
                    "error":str(e)
                }
            )
        )


if __name__=="__main__":
    main()