#!/usr/bin/env python3
"""Materialize Capivara-owned systemd units from validated local runtime specs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from adapters.systemd import unit_for_instance
from .base import InstanceRuntimeMaterializer, MaterializerError

Runner = Callable[[list[str], int], tuple[int, str, str]]
_GENERATED_BY = "capivara-instance-runtime-v1"


def _default_runner(command: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _working_directory(value: Any) -> str:
    path = str(value or "").strip()
    if not path.startswith("/"):
        raise MaterializerError("systemd WorkingDirectory must be an absolute path")
    if any(character in path for character in ("\x00", "\n", "\r")):
        raise MaterializerError("systemd WorkingDirectory contains invalid characters")
    return path


def _instance_state(instance_id: str) -> tuple[str, str]:
    token = str(instance_id or "").strip()
    if not token or any(character in token for character in ("/", "\\", "\x00", "\n", "\r")):
        raise MaterializerError("invalid systemd instance state directory")
    relative = f"capivara-instances/{token}"
    return relative, f"/var/lib/{relative}"


def _unit_dir() -> Path:
    return Path(os.environ.get("CAPIVARA_INSTANCE_SYSTEMD_DIR", "/etc/systemd/system"))


def unit_path_for_spec(spec: dict[str, Any]) -> Path:
    return _unit_dir() / unit_for_instance(spec)


def render_unit(spec: dict[str, Any]) -> str:
    instance_id = str(spec["instance_id"])
    agent_id = str(spec["agent_id"])
    runtime_id = str(spec["runtime_id"])
    state_directory, home_directory = _instance_state(instance_id)
    argv = [str(spec["executable"]), *[str(item) for item in spec.get("arguments", [])]]
    lines = [
        "[Unit]",
        f"Description=Capivara instance {instance_id}",
        "After=network-online.target",
        "Wants=network-online.target",
        f"X-Capivara-GeneratedBy={_GENERATED_BY}",
        f"X-Capivara-Instance={instance_id}",
        f"X-Capivara-Agent={agent_id}",
        f"X-Capivara-Runtime={runtime_id}",
        "",
        "[Service]",
        "Type=simple",
        f"User={spec['user']}",
        f"StateDirectory={state_directory}",
        "StateDirectoryMode=0700",
        f"WorkingDirectory={_working_directory(spec['working_directory'])}",
        f"Environment={_quote(f'HOME={home_directory}')}",
        f"Environment={_quote(f'XDG_DATA_HOME={home_directory}/.local/share')}",
        f"Environment={_quote(f'XDG_CACHE_HOME={home_directory}/.cache')}",
        f"Environment={_quote(f'XDG_CONFIG_HOME={home_directory}/.config')}",
        "ExecStart=" + " ".join(_quote(item) for item in argv),
        "Restart=no",
        "KillSignal=SIGTERM",
        "TimeoutStopSec=60",
    ]
    for key, value in sorted(dict(spec.get("environment", {})).items()):
        lines.append(f"Environment={_quote(f'{key}={value}')}")
    lines.extend(["", "[Install]", "WantedBy=multi-user.target", ""])
    return "\n".join(lines)


def _owned_content(content: str, spec: dict[str, Any]) -> bool:
    required = {
        f"X-Capivara-GeneratedBy={_GENERATED_BY}",
        f"X-Capivara-Instance={spec['instance_id']}",
        f"X-Capivara-Agent={spec['agent_id']}",
    }
    lines = {line.strip() for line in content.splitlines()}
    return required.issubset(lines)


class SystemdMaterializer(InstanceRuntimeMaterializer):
    name = "systemd"

    def __init__(self, runner: Runner | None = None):
        self.runner = runner or _default_runner

    def inspect(self, spec: dict[str, Any]) -> dict[str, Any]:
        path = unit_path_for_spec(spec)
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"materializer": self.name, "unit": path.name, "path": str(path), "exists": False, "owned": False, "matches": False}
        except OSError as exc:
            raise MaterializerError(str(exc)) from exc
        expected = render_unit(spec)
        return {
            "materializer": self.name,
            "unit": path.name,
            "path": str(path),
            "exists": True,
            "owned": _owned_content(content, spec),
            "matches": content == expected,
        }

    def _reload(self) -> None:
        code, stdout, stderr = self.runner(["systemctl", "daemon-reload"], 30)
        if code != 0:
            raise MaterializerError((stderr or stdout or "systemctl daemon-reload failed")[:2000])

    def apply(self, spec: dict[str, Any]) -> dict[str, Any]:
        path = unit_path_for_spec(spec)
        before = self.inspect(spec)
        if before["exists"] and not before["owned"]:
            raise MaterializerError(f"refusing to replace non-Capivara unit: {path.name}")
        content = render_unit(spec)
        if before["matches"]:
            return {"action": "materialize", "changed": False, "idempotent": True, "state": before}
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(content, encoding="utf-8")
            os.chmod(temp, 0o644)
            os.replace(temp, path)
            self._reload()
        except Exception:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise
        after = self.inspect(spec)
        if not after["owned"] or not after["matches"]:
            raise MaterializerError("materialized unit failed ownership validation")
        return {"action": "materialize", "changed": True, "idempotent": False, "state": after}

    def remove(self, spec: dict[str, Any]) -> dict[str, Any]:
        path = unit_path_for_spec(spec)
        before = self.inspect(spec)
        if not before["exists"]:
            return {"action": "remove", "changed": False, "idempotent": True, "state": before}
        if not before["owned"]:
            raise MaterializerError(f"refusing to remove non-Capivara unit: {path.name}")
        try:
            path.unlink()
        except OSError as exc:
            raise MaterializerError(str(exc)) from exc
        self._reload()
        return {"action": "remove", "changed": True, "idempotent": False, "state": self.inspect(spec)}


__all__ = ["SystemdMaterializer", "render_unit", "unit_path_for_spec"]
