#!/usr/bin/env python3
"""Reconcile persisted game-data inventory with the Agent filesystem."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from game_data_integrity import inspect_game_data
from game_data_state import GAME_DATA_ROOT, GAME_STATE_ROOT, list_game_data, write_json

def reconcile_game_data() -> dict[str, Any]:
    items=[]; known_paths=set(); missing=degraded=healthy=0
    for state in list_game_data():
        target_text=str(state.get("target_path") or "").strip(); target=Path(target_text).resolve() if target_text else None
        integrity=inspect_game_data(target, {"executable": state.get("executable")}) if target else {"health":"missing","exists":False,"files":0,"bytes":0}
        item={**state,"integrity":integrity,"health":integrity.get("health")}
        if target:
            known_paths.add(str(target))
        if integrity.get("health")=="ok": healthy+=1
        elif integrity.get("health")=="missing": missing+=1
        else: degraded+=1
        game=str(state.get("game") or "").strip()
        if game:
            write_json(GAME_STATE_ROOT/f"{game}.json",item)
        items.append(item)
    orphans=[]
    if GAME_DATA_ROOT.is_dir():
        for game_dir in GAME_DATA_ROOT.iterdir():
            if not game_dir.is_dir(): continue
            for target in game_dir.iterdir():
                if target.is_dir() and str(target.resolve()) not in known_paths:
                    orphans.append({"game":game_dir.name,"target_path":str(target.resolve()),"health":"orphaned","integrity":inspect_game_data(target)})
    return {"items":items,"healthy":healthy,"degraded":degraded,"missing":missing,"orphans":orphans,"orphaned":len(orphans)}

__all__=["reconcile_game_data"]
