#!/usr/bin/env python3

# =============================================================
# DSM Combat Parser
# Interpretar eventos de combate no RPT
# =============================================================


import sys
import json
import time
import re



def parse(line):

    event="UNKNOWN"

    killer="UNKNOWN"

    victim="UNKNOWN"

    weapon="UNKNOWN"

    distance=0



    text=line.lower()



    if "suicide" in text:

        event="PLAYER_SUICIDE"


    elif "killed" in text:

        event="PLAYER_KILL"



    elif "died" in text:

        event="PLAYER_DEATH"



    # jogador morto

    players=re.findall(
        r'Player[: ]+([A-Za-z0-9_-]+)',
        line
    )


    if len(players)>=2:

        killer=players[0]

        victim=players[1]


    elif len(players)==1:

        victim=players[0]



    # arma

    weapon_match=re.search(
        r'weapon[: ]+([A-Za-z0-9_-]+)',
        line,
        re.I
    )


    if weapon_match:

        weapon=weapon_match.group(1)



    # distância

    distance_match=re.search(
        r'distance[: ]+([0-9]+)',
        line,
        re.I
    )


    if distance_match:

        distance=int(
            distance_match.group(1)
        )



    return {

        "type":event,

        "category":"combat",

        "source":"combat_engine",

        "timestamp":int(time.time()),

        "data":
        {

            "killer":killer,

            "victim":victim,

            "weapon":weapon,

            "distance":distance,

            "raw":line.strip()

        }

    }



def main():

    line=sys.stdin.read().strip()


    if line:

        print(
            json.dumps(
                parse(line),
                indent=4
            )
        )



if __name__=="__main__":

    main()