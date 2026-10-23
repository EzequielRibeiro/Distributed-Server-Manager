#!/usr/bin/env python3
"""Read-only report of systemd game-unit eligibility; never authorizes no-drain."""
from __future__ import annotations
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import subprocess

name="game_uptime_guard"
loader=SourceFileLoader(name,str(Path(__file__).with_name("game-uptime-guard.py")))
spec=importlib.util.spec_from_loader(name,loader)
assert spec is not None
guard=importlib.util.module_from_spec(spec)
loader.exec_module(guard)


def report(list_units=None, inspect=None):
    list_units = list_units or _list_units
    inspect = inspect or guard.inspect
    try:
        units=list_units()
        if not isinstance(units,list) or any(not guard.UNIT.fullmatch(x) for x in units):
            raise guard.GateError("invalid active game unit inventory")
        items=[]
        for unit in sorted(set(units)):
            try:
                identity=inspect(unit)
                items.append({"unit":unit,"eligible":False,"identity_verified":True,
                              "main_pid":identity["main_pid"],
                              "reason":"no-drain transaction is not implemented"})
            except (guard.GateError,OSError,ValueError,KeyError) as exc:
                items.append({"unit":unit,"eligible":False,"identity_verified":False,
                              "reason":str(exc)[:240]})
        return {"kind":"CapivaraGameUptimeUnitReport","schema_version":1,
                "mode":"read_only","live_no_drain_authorized":False,
                "managed_active_units":len(items),"units":items}
    except (guard.GateError,OSError,ValueError,subprocess.SubprocessError) as exc:
        return {"kind":"CapivaraGameUptimeUnitReport","schema_version":1,
                "mode":"read_only","live_no_drain_authorized":False,
                "inventory_error":str(exc)[:240],"units":[]}


def _list_units():
    result=subprocess.run(
        ["systemctl","list-units","--type=service","--state=active","--all",
         "--no-legend","--plain","capivara-instance-*.service"],
        capture_output=True,text=True,check=False,timeout=8)
    if result.returncode:
        raise guard.GateError("systemd active game inventory failed")
    units=[]
    for line in result.stdout.splitlines():
        fields=line.split()
        if not fields:
            continue
        unit=fields[0]
        if not guard.UNIT.fullmatch(unit):
            raise guard.GateError("malformed systemd game unit")
        units.append(unit)
    return units


if __name__=="__main__":
    print(json.dumps(report(),ensure_ascii=False))
