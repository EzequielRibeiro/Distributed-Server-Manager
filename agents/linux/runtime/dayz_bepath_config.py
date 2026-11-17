"""Strict DayZ BattlEye RuntimeSpec projection; no OS writes or process actions."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

_BE_SUBDIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,63}){0,2}$")


def _prepare_battleye_spec(record:dict[str,Any], value:Any)->dict[str,Any]:
    """Change only the profile-owned BattlEye path, preserving map/mod state."""
    from runtime_spec import validate_runtime_spec
    if not isinstance(value,str) or _BE_SUBDIR.fullmatch(value) is None:
        raise ValueError("invalid private BattlEye directory")
    if str(record.get("game_id") or "").lower()!="dayz":
        raise ValueError("BattlEye configuration requires DayZ")
    root_value=record.get("instance_state_root")
    if not isinstance(root_value,str) or not root_value.startswith("/"):
        raise ValueError("DayZ instance private state root missing")
    root=Path(root_value)
    if root.is_symlink() or ".." in root.parts:
        raise ValueError("unsafe DayZ instance state root")
    old_value=record.get("battleye_directory","battleye")
    if not isinstance(old_value,str) or _BE_SUBDIR.fullmatch(old_value) is None:
        raise ValueError("previous BattlEye path is unsafe")
    old=str(root/old_value)
    new=str(root/value)
    if not Path(new).is_relative_to(root):
        raise ValueError("BattlEye path escaped private state root")
    # Reject existing symlink components; a privileged materializer may create
    # missing private directories, but may not follow links into other tenants.
    for sub in Path(value).parts:
        root=root/sub
        if root.is_symlink():
            raise ValueError("BattlEye private path contains a symlink")
    result=dict(record)
    previous_args=list(record.get("arguments") or [])
    def replace_owned(values):
        if not isinstance(values,list):
            raise ValueError("invalid DayZ managed arguments")
        matches=[i for i,arg in enumerate(values)
                 if isinstance(arg,str) and re.match(r"(?i)^-bepath(?:=|\s|$)",arg)]
        if len(matches)!=1 or values[matches[0]]!=f"-BEpath={old}":
            raise ValueError("DayZ BattlEye argument is not the expected profile-owned path")
        updated=list(values)
        updated[matches[0]]=f"-BEpath={new}"
        return updated
    result["arguments"]=replace_owned(previous_args)
    if "content_base_arguments" in record:
        result["content_base_arguments"]=replace_owned(record["content_base_arguments"])
    writable=record.get("writable_directories")
    if not isinstance(writable,list) or writable.count(old)!=1:
        raise ValueError("DayZ BattlEye writable directory does not match the managed spec")
    if new!=old and new in writable:
        raise ValueError("BattlEye path collides with another writable directory")
    result["writable_directories"]=[new if item==old else item for item in writable]
    context=record.get("profile_context")
    if not isinstance(context,dict):
        raise ValueError("DayZ structured profile context missing")
    result["profile_context"]={**context,"battleye_directory":value}
    result["battleye_directory"]=value
    # Validation must not rewrite any unrelated persisted flags or shared data.
    normalized=validate_runtime_spec(result,expected_agent_id=str(record["agent_id"]))
    return normalized
