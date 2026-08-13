import re
from pathlib import Path
import json
import time


LOG_DIR = Path(
    "/home/mine/steamcmd/serverfiles/profiles"
)


OUTPUT = Path(
    "/opt/dsm/dashboard/state/death_events.json"
)



def get_latest_rpt():

    files = sorted(
        LOG_DIR.glob("*.RPT"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

    return files[0] if files else None



def parse_deaths(lines):

    deaths = []


    for line in lines:


        # Exemplo genérico DayZ
        if "killed" in line.lower() or "died" in line.lower():

            deaths.append({

                "time": time.strftime(
                    "%H:%M:%S"
                ),

                "message": line.strip(),

                "type": "death"

            })


    return deaths[-20:]



def main():

    rpt = get_latest_rpt()

    if not rpt:
        return


    with rpt.open(
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as f:

        lines = f.readlines()


    data = {

        "updated_at": time.time(),

        "total":
            len(parse_deaths(lines)),

        "events":
            parse_deaths(lines)

    }


    OUTPUT.write_text(
        json.dumps(
            data,
            indent=4
        )
    )



if __name__ == "__main__":
    main()