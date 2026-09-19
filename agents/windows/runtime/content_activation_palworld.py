"""Windows-only Palworld Workshop activation for Capivara managed content."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PACKAGE=re.compile(r"^[A-Za-z0-9._-]{1,191}$")


class PalworldContentActivationError(ValueError):
    pass


def _server_compatible(value:Any)->bool:
    if isinstance(value,dict):
        for key,item in value.items():
            if str(key).replace("_","").lower()=="isserver" and item is True:
                return True
            if _server_compatible(item):
                return True
    elif isinstance(value,list):
        return any(_server_compatible(item) for item in value)
    return False


def _package_name(path:Path)->str:
    info=path/"Info.json"
    try:
        payload=json.loads(info.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise PalworldContentActivationError("Palworld Workshop item is missing a valid Info.json") from exc
    if not isinstance(payload,dict):
        raise PalworldContentActivationError("Palworld Workshop Info.json must be an object")
    package=str(payload.get("PackageName") or "").strip()
    if not _PACKAGE.fullmatch(package):
        raise PalworldContentActivationError("Palworld Workshop Info.json has an invalid PackageName")
    rules=payload.get("InstallRules")
    if not _server_compatible(rules):
        raise PalworldContentActivationError("Palworld Workshop item is not declared as server-compatible")
    return package


def project_palworld_activation(spec:dict[str,Any],entries:list[dict[str,Any]])->dict[str,Any]:
    environment=str(spec.get("environment_id") or "").strip().lower()
    if environment!="palworld.windows-modded":
        if entries:
            raise PalworldContentActivationError("Palworld managed mods require the Windows modded runtime")
        return {"arguments":[],"packages":[],"workshop_root":None}

    packages=[]
    roots=set()
    for entry in entries:
        activation=entry.get("activation") if isinstance(entry.get("activation"),dict) else {}
        adapter=str(activation.get("adapter") or "").strip().lower()
        if adapter!="palworld":
            continue
        if str(entry.get("content_type") or "").strip().lower()!="workshop":
            raise PalworldContentActivationError("Palworld modded runtime accepts only Workshop content")
        path=Path(str(entry.get("managed_path") or "")).resolve(strict=False)
        if not path.is_dir():
            raise PalworldContentActivationError("Palworld Workshop payload is unavailable")
        package=_package_name(path)
        root=path.parent
        roots.add(str(root))
        if package not in packages:
            packages.append(package)

    if len(roots)>1:
        raise PalworldContentActivationError("Palworld Workshop items do not share one managed root")
    root=next(iter(roots),None)
    args=[f"-workshopdir={root}"] if root else []
    return {"arguments":args,"packages":packages,"workshop_root":root}


def materialize_palworld_settings(spec:dict[str,Any])->list[str]:
    if str(spec.get("environment_id") or "").strip().lower()!="palworld.windows-modded":
        return []
    working=Path(str(spec.get("working_directory") or "")).resolve(strict=False)
    if not working.is_dir():
        raise PalworldContentActivationError("Palworld runtime working directory is unavailable")
    mods=working/"Mods"
    target=mods/"PalModSettings.ini"
    packages=[str(v) for v in (spec.get("content_palworld_packages") or []) if _PACKAGE.fullmatch(str(v))]
    root=str(spec.get("content_palworld_workshop_root") or "").strip()
    for value in packages:
        if any(c in value for c in ("\x00","\r","\n")):
            raise PalworldContentActivationError("invalid Palworld PackageName")
    if any(c in root for c in ("\x00","\r","\n")):
        raise PalworldContentActivationError("invalid Palworld Workshop root")
    lines=["[PalModSettings]",f"bGlobalEnableMod={'true' if packages else 'false'}"]
    lines.extend(f"ActiveModList={value}" for value in packages)
    if root:
        lines.append(f"WorkshopRootDir={root}")
    mods.mkdir(parents=True,exist_ok=True)
    target.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return ["Mods/PalModSettings.ini"]


__all__=["PalworldContentActivationError","materialize_palworld_settings","project_palworld_activation"]
