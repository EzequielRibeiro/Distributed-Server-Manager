#!/usr/bin/env python3
"""Execute one queued game-data job using the full local Hybrid installer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def _steam_user(root: Path) -> str | None:
    config = root / "config" / "providers" / "steam.conf"
    if not config.is_file():
        return None
    pattern = re.compile(r'^DSM_STEAM_USER=(?:"([^"]*)"|\'([^\']*)\'|([^#\s]*))\s*$')
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in lines:
        match = pattern.match(raw.strip())
        if match:
            return next((value for value in match.groups() if value is not None), "") or None
    return None


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: hybrid_game_data_executor.py DSM_ROOT REQUEST RESULT", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    request_path = Path(sys.argv[2])
    result_path = Path(sys.argv[3])
    command = json.loads(request_path.read_text(encoding="utf-8"))
    job_id = str(command.get("job_id") or "").strip()
    selection = command.get("selection")
    if not isinstance(selection, dict):
        _write_result(result_path, {"job_id": job_id, "status": "failed", "progress": 100, "error": "runtime selection missing"})
        return 1

    _write_result(result_path, {"job_id": job_id, "status": "running", "progress": 5})
    installer = root / "installer" / "install_selection.sh"
    environment = {**os.environ, "DSM_ROOT": str(root)}
    steam_user = _steam_user(root)
    if steam_user and not environment.get("DSM_STEAM_USER"):
        environment["DSM_STEAM_USER"] = steam_user

    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False, dir=str(request_path.parent)) as handle:
            json.dump(selection, handle, indent=2, sort_keys=True)
            handle.write("\n")
            selection_path = Path(handle.name)
        try:
            completed = subprocess.run(
                [str(installer), "install-json", str(selection_path)],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=7200,
                check=False,
                env=environment,
            )
        finally:
            try:
                selection_path.unlink()
            except OSError:
                pass
        output = completed.stdout or ""
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
        if completed.returncode != 0:
            detail = output.strip().splitlines()[-1] if output.strip() else f"installer exit {completed.returncode}"
            raise RuntimeError(detail[:2000])
    except Exception as exc:
        _write_result(result_path, {"job_id": job_id, "status": "failed", "progress": 100, "error": str(exc)[:2000]})
        print(f"hybrid game-data job failed: {exc}", file=sys.stderr, flush=True)
        return 1

    _write_result(
        result_path,
        {
            "job_id": job_id,
            "status": "completed",
            "progress": 100,
            "provider": selection.get("provider"),
            "game": selection.get("game"),
            "version": selection.get("version"),
            "target_path": selection.get("install_dir"),
        },
    )
    print(f"hybrid game-data job completed: {job_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
