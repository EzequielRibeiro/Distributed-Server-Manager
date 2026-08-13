#!/usr/bin/env python3

# =============================================================
# DSM Mod Parser
# Commit 15
#
# Integração:
#
# mod_parser.py
#       |
#       +--> mod_engine.sh
#       |
#       +--> mod_state.sh
#       |
#       +--> event_manager.sh
#
# =============================================================


import sys
import json
import time
import re



def parse(line):

    text = line.lower()


    event = "MOD_EVENT"

    mod = "unknown"



    # Ordem importante:
    # KEY_MISSING precisa vir antes de MOD_MISSING

    if "key" in text and "missing" in text:

        event = "KEY_MISSING"


    elif "updated" in text:

        event = "MOD_UPDATED"


    elif "missing" in text:

        event = "MOD_MISSING"


    elif "failed" in text:

        event = "MOD_UPDATE_FAILED"



    # Detecta nome do mod
    #
    # Exemplos:
    #
    # @Expansion updated
    # @CF missing key

    match = re.search(
        r'@([A-Za-z0-9_-]+)',
        line
    )


    if match:

        mod = match.group(1)



    return {

        "type": event,

        "category": "mod",

        "source": "mod_engine",

        "timestamp": int(time.time()),


        "resource":
        {
            "mod": mod
        },


        "data":
        {
            "raw": line.strip()
        }

    }



def main():

    line = sys.stdin.read().strip()


    if line:

        print(
            json.dumps(
                parse(line),
                indent=4
            )
        )



if __name__ == "__main__":

    main()