#!/usr/bin/env python3
"""Non-destructive remote Agent connectivity checks for the Dashboard."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from core.agent_ssh_deploy import AgentDeployError, SSHDeployOptions, preflight_ssh, preflight_windows_ssh


def _authorized(user: dict[str, Any] | None) -> None:
    role=str((user or {}).get("role","")).strip().lower()
    if role not in {"admin","controller"}: raise PermissionError("Agent connection test is not permitted")


def _password_file(raw: Any) -> str | None:
    value=str(raw or "").strip()
    if not value: return None
    root=Path(os.environ.get("DSM_REMOTE_DEPLOY_SECRET_DIR","/etc/capivara/secrets/remote-deploy")).resolve()
    path=Path(value).expanduser().resolve()
    try: path.relative_to(root)
    except ValueError as exc: raise ValueError(f"password_file must be inside {root}") from exc
    return str(path)


def test_agent_connection_for_user(user: dict[str,Any]|None,payload: dict[str,Any]|None,*,ssh_runner=None) -> dict[str,Any]:
    _authorized(user)
    if not isinstance(payload,dict): raise ValueError("payload must be an object")
    if payload.get("password") not in (None,"") or payload.get("ssh_password") not in (None,""):
        raise ValueError("SSH passwords are never accepted directly; use password_file")
    platform=str(payload.get("platform","linux")).strip().lower()
    if platform not in {"linux","windows"}: raise ValueError("unsupported Agent platform")
    host=str(payload.get("ssh_host","") or "").strip(); ssh_user=str(payload.get("ssh_user","") or "").strip()
    if not host: raise ValueError("ssh_host is required")
    if not ssh_user: raise ValueError("ssh_user is required")
    try: port=int(payload.get("ssh_port",22) or 22)
    except (TypeError,ValueError) as exc: raise ValueError("ssh_port must be an integer") from exc
    options=SSHDeployOptions(host=host,ssh_user=ssh_user,ssh_port=port,password_file=_password_file(payload.get("password_file")))
    try:
        fn=preflight_windows_ssh if platform=="windows" else preflight_ssh
        result=fn(options) if ssh_runner is None else fn(options,runner=ssh_runner)
    except AgentDeployError as exc: raise ValueError(str(exc)) from exc
    return {"ok":True,"host":host,"ssh_user":ssh_user,"ssh_port":port,"platform":result.get("platform",platform),"architecture":result.get("architecture"),"transport":"openssh","authentication":"password-file" if options.password_file else "ssh-key-or-agent"}
