"""Steam build probe for Hybrid jobs; never modifies managed game installations."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_APP_ID = re.compile(r"[0-9]{1,20}")
_BRANCH = re.compile(r"[A-Za-z0-9._-]{1,64}")
_BUILD = re.compile(r'"buildid"\s+"([0-9]+)"', re.I)


def probe(selection: dict) -> dict:
    install = selection.get("install")
    if not isinstance(install, dict):
        raise ValueError("read_only_version_probe_missing_metadata")
    app_id = str(install.get("package_id") or "").strip()
    branch = str(install.get("branch") or selection.get("branch") or "public").strip()
    if not _APP_ID.fullmatch(app_id):
        raise ValueError("read_only_version_probe_invalid_app_id")
    if not _BRANCH.fullmatch(branch):
        raise ValueError("read_only_version_probe_invalid_branch")
    target = Path(str(selection.get("install_dir") or ""))
    if not target.is_absolute() or not target.is_dir():
        raise ValueError("read_only_version_probe_missing_target")
    # Do not use HOME or global Steam manifests: those can belong to another game installation.
    installed = None
    for manifest in (target / "steamapps" / f"appmanifest_{app_id}.acf",
                     target.parent / "steamapps" / f"appmanifest_{app_id}.acf"):
        try:
            match = _BUILD.search(manifest.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if match:
            installed = match.group(1)
            break
    steamcmd = shutil.which("steamcmd")
    if not steamcmd and Path("/usr/games/steamcmd").is_file():
        steamcmd = "/usr/games/steamcmd"
    if not steamcmd:
        raise RuntimeError("read_only_version_probe_steamcmd_unavailable")
    completed = subprocess.run(
        [steamcmd, "+login", "anonymous", "+app_info_update", "1",
         "+app_info_print", app_id, "+quit"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=180, check=False,
    )
    if completed.returncode:
        raise RuntimeError("read_only_version_probe_steam_lookup_failed")
    # Parse only the selected branch block, not a different Steam branch.
    pending = False
    inside = False
    depth = 0
    available = None
    in_branches = False
    branches_pending = False
    branches_depth = 0
    for raw in (completed.stdout or "").splitlines():
        line = raw.strip()
        if not in_branches:
            if line == '"branches"':
                branches_pending = True
                continue
            if branches_pending:
                if line == "{":
                    in_branches, branches_depth = True, 1
                branches_pending = False
            continue
        if not inside:
            if line == '"' + branch + '"':
                pending = True
                continue
            if pending and line == "{":
                inside, depth, pending = True, 1, False
                continue
            pending = False
            branches_depth += line.count("{") - line.count("}")
            if branches_depth <= 0:
                break
            continue
        depth += line.count("{") - line.count("}")
        match = _BUILD.search(line)
        if match:
            available = match.group(1)
            break
        if depth <= 0:
            inside = False
            branches_depth -= 1
    if not available:
        raise RuntimeError("read_only_version_probe_metadata_unavailable")
    return {
        "schema_version": 1, "provider": "steam", "detector_supported": True,
        "app_id": app_id, "branch": branch, "installed_version": installed,
        "available_version": available,
        "state": "unknown" if not installed else "up_to_date" if installed == available else "update_available",
        "rollback_supported": True,
    }
