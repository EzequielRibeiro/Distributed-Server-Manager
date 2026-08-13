#!/usr/bin/env python3

# =============================================================
# DSM Player Parser
# Interpretar linhas do RPT e extrair jogador.
# =============================================================


import sys
import re
import json
import time



def parse(line):

    event="UNKNOWN"

    player="UNKNOWN"



    if "connected" in line.lower():

        event="PLAYER_JOIN"



    elif "disconnected" in line.lower():

        event="PLAYER_LEAVE"



    elif "suicide" in line.lower():

        event="PLAYER_SUICIDE"



    elif "died" in line.lower():

        event="PLAYER_DEATH"



    match=re.search(
        r'Player[: ]+([A-Za-z0-9_-]+)',
        line
    )


    if match:

        player=match.group(1)



    return {

        "type":event,

        "category":"player",

        "source":"dayz_parser",

        "timestamp":int(time.time()),

        "data":
        {
            "player":player,
            "raw":line.strip()
        }

    }



def main():

    line=sys.stdin.read().strip()


    if not line:

        return



    print(
        json.dumps(
            parse(line),
            indent=4
        )
    )



if __name__=="__main__":

    main()