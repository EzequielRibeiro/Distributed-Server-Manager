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

    # Verification must never enter install-json, which mutates game files.
    if str(command.get("action") or "").strip().lower() == "verify":
        try:
            provider = str(selection.get("provider") or "").strip().lower()
            if provider != "steam":
                raise ValueError("read_only_version_probe_unsupported_provider")
            from hybrid_steam_version_probe import probe
            status = probe(selection)
            target = Path(str(selection.get("install_dir")))
            _write_result(result_path, {
                "job_id": job_id, "status": "completed", "progress": 100,
                "provider": provider, "game": selection.get("game"),
                "target_path": str(target), "update_status": status,
            })
            return 0
        except Exception as exc:
            _write_result(result_path, {
                "job_id": job_id, "status": "failed", "progress": 100,
                "error": str(exc)[:2000],
            })
            return 1

    # Never route instance-scoped updates through install-json: it ignores
    # the registered instance target and cannot report transactional readiness.
    # Until the Hybrid privileged transaction bridge is wired, fail closed.
    meta = selection.get("_server_update")
    if str(command.get("action") or "").strip().lower() == "update" and isinstance(meta, dict):
        _write_result(result_path, {
            "job_id": job_id, "status": "failed", "progress": 100,
            "error": "hybrid_instance_update_transaction_unavailable",
        })
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
        # Only DSM-controlled diagnostics/progress may enter the job log.
        # Do not forward untrusted installer/SteamCMD transcript verbatim.
        safe_lines = [line for line in output.splitlines()
                      if line.startswith("[DSM][STEAM][ERRO]")
                      or line.startswith("[DSM][INSTALL][ERRO]")]
        for line in safe_lines:
            if re.search(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|cookie|steamguard|steam guard code)", line):
                print("[DSM][INSTALL][ERRO] provider error redacted", flush=True)
            else:
                print(line, flush=True)
        if completed.returncode != 0:
            # Preserve the actionable provider error, rather than only the
            # generic final INSTALL-ERROR status line. Do not persist the full
            # SteamCMD transcript (it can contain account/session details).
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            provider_errors = [
                line for line in lines
                if "[DSM][STEAM][ERRO]" in line or "[DSM][INSTALL][ERRO]" in line
            ]
            generic = next((line for line in reversed(lines)
                if re.fullmatch(r"\[DSM\]\[INSTALL-ERROR\] action=[a-z_-]+ error=[a-z_-]+ status=[a-z_-]+", line)), None)
            detail = provider_errors[-1] if provider_errors else (generic or f"installer exit {completed.returncode}")
            # Fail closed if the selected diagnostic contains possible secrets.
            # The full installer transcript is available only in the local job log.
            if re.search(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|cookie|steamguard|steam guard code)", detail):
                detail = f"installer failed (exit {completed.returncode}); inspect protected job log"
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
